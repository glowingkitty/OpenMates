//! Cancellable preparation, deferred critical transactions, and bounded tool I/O.
use super::*;
use std::{
    cell::RefCell,
    fs::File,
    io::ErrorKind,
    process::Child,
    time::{Duration, Instant},
};
use tokio_util::sync::CancellationToken;
thread_local! {static CURRENT:RefCell<Option<Context>>=const{RefCell::new(None)};}
struct Context {
    cancel: CancellationToken,
    critical: usize,
    deferred: bool,
}
pub(super) struct Scope(Option<Context>);
impl Scope {
    pub(super) fn new(caller: &CancellationToken) -> Self {
        Self(CURRENT.with(|c| {
            c.borrow_mut().replace(Context {
                cancel: caller.child_token(),
                critical: 0,
                deferred: false,
            })
        }))
    }
}
impl Drop for Scope {
    fn drop(&mut self) {
        CURRENT.with(|c| {
            if let Some(context) = c.borrow_mut().take() {
                context.cancel.cancel();
            }
            *c.borrow_mut() = self.0.take();
        })
    }
}
pub(super) fn check() -> Result<()> {
    CURRENT.with(|c| {
        if let Some(context) = c.borrow_mut().as_mut()
            && context.cancel.is_cancelled()
        {
            if context.critical == 0 {
                return Err(Error::Cancelled);
            }
            context.deferred = true;
        }
        Ok(())
    })
}
pub(super) struct Critical(bool);
pub(super) fn critical() -> Result<Critical> {
    check()?;
    Ok(Critical(CURRENT.with(|c| {
        if let Some(context) = c.borrow_mut().as_mut() {
            context.critical += 1;
            true
        } else {
            false
        }
    })))
}
impl Drop for Critical {
    fn drop(&mut self) {
        if self.0 {
            CURRENT.with(|c| {
                if let Some(context) = c.borrow_mut().as_mut() {
                    context.deferred |= context.cancel.is_cancelled();
                    context.critical = context.critical.saturating_sub(1);
                }
            })
        }
    }
}
pub(super) fn finish(action: &str, state: &Path, result: Result<Value>) -> Result<Value> {
    let cancelled = CURRENT.with(|c| {
        c.borrow()
            .as_ref()
            .filter(|c| c.cancel.is_cancelled())
            .map(|c| c.deferred)
    });
    if let Some(deferred) = cancelled {
        fs::write(
            &state.join("server-cancellation.json"),
            &serde_json::to_vec_pretty(
                &json!({"command":action,"status":"cancelled","safeCheckpointReached":true,"operationCompleted":result.is_ok(),"cancellationDeferred":deferred,"completedAt":now()}),
            )?,
            0o600,
        )?;
        match result {
            Ok(value) => {
                let mut value = if value.is_object() {
                    value
                } else {
                    json!({"result":value})
                };
                value["cancelled"] = json!(true);
                value["safeCheckpointReached"] = json!(true);
                value["cancellationDeferred"] = json!(deferred);
                Ok(value)
            }
            Err(_) => Err(Error::Cancelled),
        }
    } else {
        result
    }
}
struct Process {
    child: Child,
    pid: rustix::process::Pid,
    reaped: bool,
    isolated: bool,
}
impl Process {
    fn ended(&self) -> Result<bool> {
        use rustix::process::{WaitId, WaitIdOptions};
        // Retain the child as a zombie until its group has been terminated, so
        // its PID/PGID cannot be reused for an unrelated process group.
        rustix::process::waitid(
            WaitId::Pid(self.pid),
            WaitIdOptions::EXITED | WaitIdOptions::NOHANG | WaitIdOptions::NOWAIT,
        )
        .map(|s| s.is_some())
        .map_err(|_| Error::Io)
    }
    fn signal(&self, signal: rustix::process::Signal) {
        if self.isolated {
            let _ = rustix::process::kill_process_group(self.pid, signal);
        } else {
            let _ = rustix::process::kill_process(self.pid, signal);
        }
    }
    fn reap(&mut self) -> Result<bool> {
        self.signal(rustix::process::Signal::KILL);
        let status = self.child.wait()?;
        self.reaped = true;
        Ok(status.success())
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        if !self.reaped {
            self.signal(rustix::process::Signal::KILL);
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}
fn nonblocking(fd: impl std::os::fd::AsFd) -> Result<()> {
    let flags = rustix::fs::fcntl_getfl(&fd).map_err(|_| Error::Io)?;
    rustix::fs::fcntl_setfl(&fd, flags | rustix::fs::OFlags::NONBLOCK).map_err(|_| Error::Io)
}
#[derive(Clone, Copy)]
enum Stop {
    Cancelled,
    Timeout,
    Output,
    Pipe,
    Io,
    Rejected(Error),
}
pub(super) struct InputStage {
    pub(super) input: Zeroizing<Vec<u8>>,
    pub(super) validate: fn(&[u8]) -> Result<()>,
}
struct Dialogue<'a> {
    stages: &'a [InputStage],
    current: usize,
    offset: usize,
    reply_start: usize,
}
impl<'a> Dialogue<'a> {
    fn new(stages: &'a [InputStage]) -> Result<Self> {
        let bytes = stages
            .iter()
            .try_fold(0usize, |sum, stage| sum.checked_add(stage.input.len()))
            .ok_or(Error::Protocol)?;
        if stages.is_empty()
            || stages.len() > 32
            || bytes > 8 * 1024 * 1024
            || stages.iter().any(|stage| {
                !stage.input.ends_with(b"\n")
                    || stage.input[..stage.input.len() - 1].contains(&b'\n')
            })
        {
            return Err(Error::Protocol);
        }
        Ok(Self {
            stages,
            current: 0,
            offset: 0,
            reply_start: 0,
        })
    }
    fn receive(&mut self, output: &[u8]) -> Result<()> {
        let pending = &output[self.reply_start..];
        if pending.is_empty() {
            return Ok(());
        }
        let stage = self.stages.get(self.current).ok_or(Error::Protocol)?;
        if self.offset != stage.input.len() {
            return Err(Error::Protocol);
        }
        if let Some(end) = pending.iter().position(|b| *b == b'\n') {
            // Surplus complete or partial frames must be rejected before any
            // later command is made available to the child's stdin.
            if end + 1 != pending.len() {
                return Err(Error::Protocol);
            }
            (stage.validate)(&pending[..end])?;
            self.current += 1;
            self.offset = 0;
            self.reply_start = output.len();
        }
        Ok(())
    }
    fn complete(&self) -> bool {
        self.current == self.stages.len()
    }
}
#[cfg(test)]
pub(super) fn validate_staged_output(stages: &[InputStage], output: &[u8]) -> Result<()> {
    Dialogue::new(stages)?;
    if output.len() > 1024 * 1024 {
        return Err(Error::Protocol);
    }
    let mut lines = output
        .strip_suffix(b"\n")
        .ok_or(Error::Protocol)?
        .split(|b| *b == b'\n');
    for stage in stages {
        (stage.validate)(lines.next().ok_or(Error::Protocol)?)?;
    }
    if lines.next().is_some() {
        return Err(Error::Protocol);
    }
    Ok(())
}
fn drive(
    command: Command,
    input: Option<&[u8]>,
    capture: bool,
    timeout: Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    drive_with(command, input, capture, timeout, true)
}
fn drive_with(
    command: Command,
    input: Option<&[u8]>,
    capture: bool,
    timeout: Duration,
    isolated: bool,
) -> Result<Zeroizing<Vec<u8>>> {
    drive_protocol(command, input, capture, timeout, isolated, None)
}
fn drive_protocol(
    mut command: Command,
    input: Option<&[u8]>,
    capture: bool,
    timeout: Duration,
    isolated: bool,
    stages: Option<&[InputStage]>,
) -> Result<Zeroizing<Vec<u8>>> {
    use std::os::unix::process::CommandExt;
    check()?;
    let mut dialogue = stages.map(Dialogue::new).transpose()?;
    if isolated {
        command.process_group(0);
    }
    let child = command
        .spawn()
        .map_err(|_| Error::Invalid("Required system tool could not be started."))?;
    let pid = rustix::process::Pid::from_raw(child.id() as i32).ok_or(Error::Io)?;
    let mut process = Process {
        child,
        pid,
        reaped: false,
        isolated,
    };
    let mut stdout = process.child.stdout.take();
    if let Some(pipe) = &stdout {
        nonblocking(pipe)?;
    }
    let mut stdin = process.child.stdin.take();
    if let Some(pipe) = &stdin {
        nonblocking(pipe)?;
    }
    let input = input.unwrap_or_default();
    let mut offset = 0usize;
    let mut output = Zeroizing::new(Vec::new());
    let start = Instant::now();
    let mut ended_at = None;
    let mut stopping: Option<(Stop, Instant)> = None;
    let mut killed = false;
    let mut block = Zeroizing::new([0; 65536]);
    loop {
        if let Some(pipe) = stdout.as_mut() {
            // Fair bounded drains let cancellation/deadline checks run even if
            // a child writes continuously faster than the reader.
            for _ in 0..16 {
                match pipe.read(&mut *block) {
                    Ok(0) => {
                        stdout = None;
                        break;
                    }
                    Ok(n) => {
                        let limit = if dialogue.is_some() {
                            1024 * 1024
                        } else {
                            16 * 1024 * 1024
                        };
                        if output.len() + n > limit {
                            stopping.get_or_insert((Stop::Output, Instant::now()));
                            break;
                        }
                        output.extend_from_slice(&block[..n]);
                    }
                    Err(e) if e.kind() == ErrorKind::WouldBlock => break,
                    Err(e) if e.kind() == ErrorKind::Interrupted => continue,
                    Err(_) => {
                        stopping.get_or_insert((Stop::Io, Instant::now()));
                        stdout = None;
                        break;
                    }
                }
            }
        }
        if let Some(dialogue) = dialogue.as_mut() {
            if stopping.is_none() {
                if check().is_err() {
                    stopping = Some((Stop::Cancelled, Instant::now()));
                } else if start.elapsed() >= timeout {
                    stopping = Some((Stop::Timeout, Instant::now()));
                } else if let Err(error) = dialogue.receive(&output) {
                    stopping = Some((Stop::Rejected(error), Instant::now()));
                }
            }
            if stopping.is_none() {
                if dialogue.complete() {
                    stdin = None;
                } else if let Some(pipe) = stdin.as_mut() {
                    let stage = &dialogue.stages[dialogue.current];
                    if dialogue.offset < stage.input.len() {
                        match pipe.write(&stage.input[dialogue.offset..]) {
                            Ok(0) => {
                                stopping = Some((Stop::Io, Instant::now()));
                            }
                            Ok(n) => dialogue.offset += n,
                            Err(e)
                                if matches!(
                                    e.kind(),
                                    ErrorKind::WouldBlock | ErrorKind::Interrupted
                                ) => {}
                            Err(_) => {
                                stopping = Some((Stop::Io, Instant::now()));
                            }
                        }
                    }
                } else {
                    stopping = Some((Stop::Rejected(Error::Protocol), Instant::now()));
                }
            }
        } else if let Some(pipe) = stdin.as_mut() {
            if offset == input.len() {
                stdin = None;
            } else {
                match pipe.write(&input[offset..]) {
                    Ok(0) => {
                        stopping.get_or_insert((Stop::Io, Instant::now()));
                        stdin = None;
                    }
                    Ok(n) => offset += n,
                    Err(e)
                        if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::Interrupted) => {}
                    Err(_) => {
                        stopping.get_or_insert((Stop::Io, Instant::now()));
                        stdin = None;
                    }
                }
            }
        }
        if process.ended()? {
            let ended = ended_at.get_or_insert_with(Instant::now);
            if stdout.is_none() {
                break;
            }
            if ended.elapsed() >= Duration::from_millis(250) {
                stopping.get_or_insert((Stop::Pipe, Instant::now()));
            }
        }
        if check().is_err() {
            stopping.get_or_insert((Stop::Cancelled, Instant::now()));
        }
        if start.elapsed() >= timeout {
            stopping.get_or_insert((Stop::Timeout, Instant::now()));
        }
        if let Some((_, at)) = stopping {
            stdin = None;
            if !killed {
                process.signal(rustix::process::Signal::TERM);
            }
            if at.elapsed() >= Duration::from_millis(250) {
                process.signal(rustix::process::Signal::KILL);
                killed = true;
            }
            if at.elapsed() >= Duration::from_secs(1) {
                stdout = None;
                let _ = process.child.kill();
                break;
            }
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    // Close pipe handles before reaping so escaped descendants cannot keep any
    // application reader/writer thread alive: there are no pipe join threads.
    drop(stdout);
    drop(stdin);
    let success = process.reap()?;
    if let Some((stop, _)) = stopping {
        return Err(match stop {
            Stop::Cancelled => Error::Cancelled,
            Stop::Timeout => Error::Invalid("System operation exceeded its deadline."),
            Stop::Output => Error::Invalid("System output exceeded the safe response limit."),
            Stop::Pipe => {
                Error::Invalid("System tool left descendants holding inherited output pipes.")
            }
            Stop::Io => Error::Io,
            Stop::Rejected(error) => error,
        });
    }
    if !success {
        return Err(Error::Invalid(
            "System operation failed. Inspect server status and logs.",
        ));
    }
    if capture && offset < input.len() {
        return Err(Error::Io);
    }
    if dialogue.as_ref().is_some_and(|d| !d.complete()) {
        return Err(Error::Protocol);
    }
    Ok(output)
}
fn command(program: &str, args: &[String], cwd: &Path, input: Option<&[u8]>) -> Command {
    let mut command = Command::new(program);
    command
        .args(args)
        .current_dir(cwd)
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        });
    if program == "docker" && args.first().is_some_and(|s| s == "compose") {
        command.env("GIT_WORK_DIR", cwd);
    }
    command
}
pub(super) fn run(
    program: &str,
    args: &[String],
    cwd: &Path,
    input: Option<&[u8]>,
    timeout: Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    let mut cmd = command(program, args, cwd, input);
    cmd.stdout(Stdio::piped()).stderr(Stdio::null());
    drive(cmd, input, true, timeout)
}
pub(super) fn run_staged(
    program: &str,
    args: &[String],
    cwd: &Path,
    stages: &[InputStage],
    timeout: Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    let mut cmd = command(program, args, cwd, Some(&[]));
    cmd.stdout(Stdio::piped()).stderr(Stdio::null());
    drive_protocol(cmd, None, true, timeout, true, Some(stages))
}
#[cfg(test)]
pub(super) fn test_staged(
    mut command: Command,
    stages: &[InputStage],
    timeout: Duration,
) -> Result<Zeroizing<Vec<u8>>> {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    drive_protocol(command, None, true, timeout, true, Some(stages))
}
pub(super) fn to_file(
    program: &str,
    args: &[String],
    cwd: &Path,
    output: &File,
    timeout: Duration,
) -> Result<()> {
    let mut cmd = command(program, args, cwd, None);
    cmd.stdout(Stdio::from(output.try_clone()?))
        .stderr(Stdio::null());
    drive(cmd, None, false, timeout)?;
    Ok(())
}
pub(super) fn inherit(program: &str, args: &[String], cwd: &Path, timeout: Duration) -> Result<()> {
    let mut cmd = command(program, args, cwd, None);
    cmd.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    drive(cmd, None, false, timeout)?;
    Ok(())
}
/// Foreground editors must retain the terminal's foreground process group.
/// They inherit I/O directly, so no descendant can retain an application pipe;
/// cancellation terminates the owned editor process without signalling the CLI.
pub(super) fn interactive(program: &str, args: &[String], cwd: &Path) -> Result<()> {
    use std::io::IsTerminal;
    struct Terminal(Option<rustix::termios::Termios>);
    impl Terminal {
        fn restore(&mut self) -> Result<()> {
            if let Some(saved) = &self.0 {
                rustix::termios::tcsetattr(
                    std::io::stdin(),
                    rustix::termios::OptionalActions::Now,
                    saved,
                )
                .map_err(|_| Error::Io)?;
                self.0 = None;
            }
            Ok(())
        }
    }
    impl Drop for Terminal {
        fn drop(&mut self) {
            let _ = self.restore();
        }
    }
    let mut terminal = Terminal(if std::io::stdin().is_terminal() {
        Some(rustix::termios::tcgetattr(std::io::stdin()).map_err(|_| Error::Io)?)
    } else {
        None
    });
    let mut cmd = command(program, args, cwd, None);
    cmd.stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    let result = drive_with(cmd, None, false, Duration::MAX, false);
    let restored = terminal.restore();
    if restored.is_err() {
        eprintln!("The editor exited, but terminal settings could not be restored.");
    }
    result?;
    restored
}
#[cfg(test)]
mod tests {
    use super::*;
    fn fixture_command(mode: &str) -> Command {
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "server::operation::tests::tool_fixture",
                "--nocapture",
            ])
            .env("OPENMATES_SERVER_TOOL_FIXTURE", mode)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        command
    }
    #[test]
    fn tool_fixture() {
        let Ok(mode) = std::env::var("OPENMATES_SERVER_TOOL_FIXTURE") else {
            return;
        };
        match mode.as_str() {
            "echo" => {
                let mut bytes = Zeroizing::new(Vec::new());
                std::io::stdin().read_to_end(&mut bytes).unwrap();
                std::io::stdout().write_all(&bytes).unwrap();
            }
            "hold" => std::thread::sleep(Duration::from_secs(60)),
            "finite" => {
                std::thread::sleep(Duration::from_millis(150));
                std::io::stdout()
                    .write_all(b"finite fixture completed")
                    .unwrap();
            }
            "pipe" => {
                let mut command = fixture_command("hold");
                command.stdin(Stdio::null()).stdout(Stdio::inherit());
                #[expect(
                    clippy::zombie_processes,
                    reason = "The fixture deliberately leaves an inherited pipe in a descendant; the isolated process-group runner must terminate it after its parent exits."
                )]
                let _child = command.spawn().unwrap();
                std::io::stdout().write_all(b"parent exiting").unwrap();
            }
            "overflow" => {
                let bytes = [b'x'; 65536];
                loop {
                    if std::io::stdout().write_all(&bytes).is_err() {
                        break;
                    }
                }
            }
            _ => panic!("unknown fixture"),
        }
    }
    #[test]
    fn bounded_nonblocking_input_output_and_inherited_pipe_cleanup() {
        let input = vec![b'x'; 1024 * 1024];
        let echoed = drive(
            fixture_command("echo"),
            Some(&input),
            true,
            Duration::from_secs(5),
        )
        .unwrap();
        assert!(echoed.windows(input.len()).any(|w| w == input));
        for (mode, timeout, reason) in [
            ("hold", Duration::from_millis(50), "deadline"),
            ("pipe", Duration::from_secs(5), "descendants"),
            ("overflow", Duration::from_secs(5), "response limit"),
        ] {
            let start = Instant::now();
            let result = drive(
                fixture_command(mode),
                if mode == "pipe" { None } else { Some(&input) },
                true,
                timeout,
            );
            assert!(
                matches!(result,Err(Error::Invalid(message))if message.contains(reason)),
                "{mode}: {:?}",
                result.as_ref().err()
            );
            assert!(start.elapsed() < Duration::from_secs(3));
        }
    }
    #[test]
    fn preparation_cancels_but_critical_tool_finishes_before_safe_checkpoint() {
        for critical in [false, true] {
            let caller = CancellationToken::new();
            let _scope = Scope::new(&caller);
            let guard = if critical {
                Some(super::critical().unwrap())
            } else {
                None
            };
            let signal = caller.clone();
            let notifier = std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(30));
                signal.cancel();
            });
            let result = drive(
                fixture_command(if critical { "finite" } else { "hold" }),
                None,
                true,
                Duration::from_secs(5),
            );
            notifier.join().unwrap();
            if critical {
                assert!(result.is_ok());
            } else {
                assert!(matches!(result, Err(Error::Cancelled)));
            }
            drop(guard);
            assert!(matches!(check(), Err(Error::Cancelled)));
        }
        let caller = CancellationToken::new();
        {
            let _scope = Scope::new(&caller);
        }
        assert!(!caller.is_cancelled());
    }
    #[test]
    fn cancelled_completion_records_safe_checkpoint_without_secrets() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::Builder::new()
            .permissions(std::fs::Permissions::from_mode(0o700))
            .tempdir()
            .unwrap();
        let caller = CancellationToken::new();
        let _scope = Scope::new(&caller);
        {
            let _critical = critical().unwrap();
            caller.cancel();
            assert!(check().is_ok());
        }
        let completed = finish(
            "update",
            dir.path(),
            Ok(json!({"status":"success","installedVersion":"fixture"})),
        )
        .unwrap();
        assert_eq!(completed["status"], "success");
        assert_eq!(completed["installedVersion"], "fixture");
        assert_eq!(completed["cancelled"], true);
        assert_eq!(completed["cancellationDeferred"], true);
        assert_eq!(completed["safeCheckpointReached"], true);
        let receipt: Value = serde_json::from_slice(
            &fs::private_read(&dir.path().join("server-cancellation.json"), 4096).unwrap(),
        )
        .unwrap();
        assert_eq!(receipt["cancellationDeferred"], true);
        assert_eq!(receipt["safeCheckpointReached"], true);
        assert_eq!(receipt["operationCompleted"], true);
    }
}
