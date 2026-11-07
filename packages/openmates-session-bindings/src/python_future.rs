//! Exit-safe Rust-future-to-asyncio bridge for the PyO3 binding (Python SDK
//! adapter only; marshals, owns no SDK logic). It wraps pyo3-async-runtimes'
//! shared tokio runtime so no tokio thread attaches to the interpreter once
//! Python exit began: an `atexit` hook closes an attach gate and waits, GIL
//! released, for in-flight completions. Later completions are dropped unattached,
//! because nothing can await them anymore.

// Why: pyo3-async-runtimes completes every awaitable on a tokio blocking thread
// that attaches (`PyGILState_Ensure`). `loop.call_soon_threadsafe` releases the
// GIL inside its self-pipe `send`, so the awaiting coroutine can resume, finish
// and start finalization while that foreign thread still has to re-attach.
// CPython 3.12 then crashes (`Fatal Python error: Segmentation fault`, no Python
// frame); abi3 builds compile out PyO3's 3.13+ `Py_IsFinalizing` check. Seen as
// the intermittent -11 adapter children in sdk-conformance (TASK-1968).
use pyo3::prelude::*;
use pyo3_async_runtimes::{TaskLocals, generic};
use std::cell::OnceCell;
use std::future::Future;
use std::pin::Pin;
use std::sync::{Condvar, Mutex, MutexGuard, PoisonError};

/// Attach-gate state: `closing` flips once at interpreter exit; `active` counts
/// foreign threads between gate admission and the end of their attach.
struct Gate {
    closing: bool,
    active: usize,
}

static GATE: Mutex<Gate> = Mutex::new(Gate {
    closing: false,
    active: 0,
});
static GATE_IDLE: Condvar = Condvar::new();

// The state is two plain counters updated without intermediate invariants, so
// a panic in another holder cannot leave it inconsistent: recover the guard.
fn gate() -> MutexGuard<'static, Gate> {
    GATE.lock().unwrap_or_else(PoisonError::into_inner)
}

tokio::task_local! {
    static TASK_LOCALS: OnceCell<TaskLocals>;
}

/// pyo3-async-runtimes adapter over its shared tokio runtime whose blocking
/// completions (the only places that attach to Python) pass the exit gate.
struct GatedTokio;

impl generic::Runtime for GatedTokio {
    type JoinError = tokio::task::JoinError;
    type JoinHandle = tokio::task::JoinHandle<()>;

    fn spawn<F>(fut: F) -> Self::JoinHandle
    where
        F: Future<Output = ()> + Send + 'static,
    {
        pyo3_async_runtimes::tokio::get_runtime().spawn(fut)
    }

    fn spawn_blocking<F>(f: F) -> Self::JoinHandle
    where
        F: FnOnce() + Send + 'static,
    {
        pyo3_async_runtimes::tokio::get_runtime().spawn_blocking(move || {
            {
                let mut state = gate();
                if state.closing {
                    // Interpreter exit already began: dropping `f` releases its
                    // Python references through PyO3's deferred pool, unattached.
                    return;
                }
                state.active += 1;
            }
            f();
            let mut state = gate();
            state.active -= 1;
            if state.active == 0 {
                GATE_IDLE.notify_all();
            }
        })
    }
}

impl generic::ContextExt for GatedTokio {
    fn scope<F, R>(locals: TaskLocals, fut: F) -> Pin<Box<dyn Future<Output = R> + Send>>
    where
        F: Future<Output = R> + Send + 'static,
    {
        let cell = OnceCell::new();
        // A fresh cell is always empty, so this set cannot fail.
        let _ = cell.set(locals);
        Box::pin(TASK_LOCALS.scope(cell, fut))
    }

    fn get_task_locals() -> Option<TaskLocals> {
        TASK_LOCALS
            .try_with(|cell| cell.get().cloned())
            .ok()
            .flatten()
    }
}

/// Drop-in for `pyo3_async_runtimes::tokio::future_into_py` (same cancellation
/// and result semantics) whose completion never attaches once exit began.
///
/// # Errors
/// Returns the Python error raised while creating the asyncio future.
pub(crate) fn future_into_py<F, T>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<T>> + Send + 'static,
    T: for<'py> IntoPyObject<'py> + Send + 'static,
{
    generic::future_into_py::<GatedTokio, _, T>(py, fut)
}

/// `atexit` hook: close the gate, then wait with the GIL released until every
/// admitted completion detached, so no foreign thread attaches during or after
/// finalization. Admitted attaches only run Python bookkeeping, so this wait is
/// short and needs the GIL we hand back.
#[pyfunction]
fn quiesce_native_completions(py: Python<'_>) {
    py.detach(|| {
        let mut state = gate();
        state.closing = true;
        while state.active > 0 {
            state = GATE_IDLE
                .wait(state)
                .unwrap_or_else(PoisonError::into_inner);
        }
    });
}

/// Registers the exit gate during module import. `atexit` runs before CPython
/// marks the runtime finalizing, after `threading` joined non-daemon threads.
///
/// # Errors
/// Returns the Python error if `atexit.register` fails.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let hook = wrap_pyfunction!(quiesce_native_completions, module)?;
    module
        .py()
        .import("atexit")?
        .call_method1("register", (hook,))?;
    Ok(())
}
