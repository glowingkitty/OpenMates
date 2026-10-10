mod model;
mod ui;

use crate::model::{Snapshot, read_frame};
use crate::ui::Ui;
use crossterm::{
    event::{
        self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
    },
    execute,
    terminal::{
        self, EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
    },
};
use ratatui::{
    Terminal, TerminalOptions, Viewport,
    backend::{CrosstermBackend, TestBackend},
    layout::Rect,
};
use serde::Serialize;
use std::{
    env,
    fs::File,
    hash::{Hash, Hasher},
    io::{self, BufRead, BufReader, Read, Write},
    os::fd::FromRawFd,
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
        mpsc,
    },
    thread,
    time::{Duration, Instant},
};

fn load_snapshot(path: &Path) -> Result<Snapshot, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut bytes = Vec::new();
    file.take(model::MAX_LINE + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > model::MAX_LINE {
        return Err("fixture too large".into());
    }
    let snapshot: Snapshot = serde_json::from_slice(&bytes)?;
    snapshot.validate()?;
    Ok(snapshot)
}

struct TerminalGuard;
impl TerminalGuard {
    fn enter() -> io::Result<Self> {
        enable_raw_mode()?;
        if let Err(error) = execute!(io::stderr(), EnterAlternateScreen, EnableMouseCapture) {
            let _ = disable_raw_mode();
            return Err(error);
        }
        Ok(Self)
    }
}
impl Drop for TerminalGuard {
    fn drop(&mut self) {
        let _ = execute!(io::stderr(), DisableMouseCapture, LeaveAlternateScreen);
        let _ = disable_raw_mode();
    }
}

fn run(
    snapshot: Snapshot,
    incoming: Option<mpsc::Receiver<Snapshot>>,
    mut outgoing: Option<File>,
) -> Result<(), Box<dyn std::error::Error>> {
    let _guard = TerminalGuard::enter()?;
    let (width, height) = terminal::size()?;
    let mut terminal = Terminal::with_options(
        CrosstermBackend::new(io::stderr()),
        TerminalOptions {
            viewport: Viewport::Fixed(Rect::new(0, 0, width, height)),
        },
    )?;
    terminal.clear()?;
    let mut ui = Ui::new(snapshot);
    let mut dirty = true;
    loop {
        if let Some(receiver) = &incoming {
            let mut disconnected = false;
            loop {
                match receiver.try_recv() {
                    Ok(snapshot) => {
                        dirty |= ui.update(snapshot);
                    }
                    Err(mpsc::TryRecvError::Empty) => break,
                    Err(mpsc::TryRecvError::Disconnected) => {
                        disconnected = true;
                        break;
                    }
                }
            }
            if disconnected {
                break;
            }
        }
        if dirty {
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
            dirty = false;
        }
        if !event::poll(Duration::from_millis(50))? {
            continue;
        }
        dirty = true;
        let intents = match event::read()? {
            Event::Key(key) if key.kind == KeyEventKind::Press => {
                if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
                    break;
                }
                ui.key(key)
            }
            Event::Mouse(mouse) => ui.mouse(mouse),
            Event::Resize(width, height) => {
                terminal.resize(Rect::new(0, 0, width, height))?;
                Vec::new()
            }
            _ => Vec::new(),
        };
        if let Some(pipe) = &mut outgoing {
            for intent in intents {
                serde_json::to_writer(&mut *pipe, &intent.action(&ui.snapshot))?;
                pipe.write_all(b"\n")?;
                pipe.flush()?;
            }
        }
    }
    Ok(())
}

fn bridge() -> Result<(), Box<dyn std::error::Error>> {
    // fd 0 belongs to Crossterm's TTY event reader, fd 2 to the terminal renderer.
    // These two inherited pipes never carry terminal bytes or credential material.
    let input = unsafe { File::from_raw_fd(3) };
    let output = unsafe { File::from_raw_fd(4) };
    let (sender, receiver) = mpsc::sync_channel::<Snapshot>(1);
    thread::spawn(move || {
        let mut reader = BufReader::new(input);
        loop {
            match read_frame(&mut reader) {
                Ok(Some(bytes)) => {
                    if let Ok(snapshot) = serde_json::from_slice::<Snapshot>(&bytes)
                        && snapshot.validate().is_ok()
                        && sender.send(snapshot).is_err()
                    {
                        break;
                    }
                }
                Ok(None) => break,
                Err(error) if error.kind() == io::ErrorKind::InvalidData => continue,
                Err(_) => break,
            }
        }
    });
    let first = receiver.recv()?;
    run(first, Some(receiver), Some(output))
}

#[derive(Clone)]
struct CountingWriter(Arc<AtomicUsize>);
impl Write for CountingWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.fetch_add(buf.len(), Ordering::Relaxed);
        Ok(buf.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BenchRow {
    width: u16,
    height: u16,
    messages: usize,
    workspace_rows: usize,
    cold_ansi_ms: f64,
    warm_ansi_ms: f64,
    changed_ansi_ms: f64,
    cold_ansi_bytes: usize,
    warm_ansi_bytes: usize,
    changed_ansi_bytes: usize,
    cold_test_ms: f64,
    warm_test_ms: f64,
    changed_test_ms: f64,
    test_snapshot_hash: String,
    projection_included: bool,
    transport_included: bool,
    iterations: usize,
}

fn average_ms(start: Instant, iterations: usize) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0 / iterations as f64
}
fn benchmark(snapshot: Snapshot) -> Result<(), Box<dyn std::error::Error>> {
    let iterations = 20;
    let mut rows = Vec::new();
    for (width, height) in [(160, 50), (240, 70)] {
        let counter = Arc::new(AtomicUsize::new(0));
        let fixed = TerminalOptions {
            viewport: Viewport::Fixed(Rect::new(0, 0, width, height)),
        };
        let mut cold_ansi_bytes = 0;
        let start = Instant::now();
        for _ in 0..iterations {
            let mut terminal = Terminal::with_options(
                CrosstermBackend::new(CountingWriter(counter.clone())),
                fixed.clone(),
            )?;
            let before = counter.load(Ordering::Relaxed);
            let mut ui = Ui::new(snapshot.clone());
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
            cold_ansi_bytes += counter.load(Ordering::Relaxed) - before;
        }
        let cold_ansi_ms = average_ms(start, iterations);
        let mut terminal = Terminal::with_options(
            CrosstermBackend::new(CountingWriter(counter.clone())),
            fixed,
        )?;
        let mut ui = Ui::new(snapshot.clone());
        terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        let before = counter.load(Ordering::Relaxed);
        let start = Instant::now();
        for _ in 0..iterations {
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        }
        let warm_ansi_ms = average_ms(start, iterations);
        let warm_ansi_bytes = counter.load(Ordering::Relaxed) - before;
        let before = counter.load(Ordering::Relaxed);
        let start = Instant::now();
        for i in 0..iterations {
            ui.draft = if i % 2 == 0 {
                "typing a draft".into()
            } else {
                "a changed draft".into()
            };
            ui.scroll_up = (i % 2) as u16;
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        }
        let changed_ansi_ms = average_ms(start, iterations);
        let changed_ansi_bytes = counter.load(Ordering::Relaxed) - before;

        let start = Instant::now();
        for _ in 0..iterations {
            let mut terminal = Terminal::new(TestBackend::new(width, height))?;
            let mut ui = Ui::new(snapshot.clone());
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        }
        let cold_test_ms = average_ms(start, iterations);
        let mut terminal = Terminal::new(TestBackend::new(width, height))?;
        let mut ui = Ui::new(snapshot.clone());
        terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        let start = Instant::now();
        for _ in 0..iterations {
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        }
        let warm_test_ms = average_ms(start, iterations);
        let start = Instant::now();
        for i in 0..iterations {
            ui.draft = if i % 2 == 0 {
                "typing a draft".into()
            } else {
                "a changed draft".into()
            };
            ui.scroll_up = (i % 2) as u16;
            terminal.draw(|frame| ui::draw(frame, &mut ui))?;
        }
        let changed_test_ms = average_ms(start, iterations);
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        format!("{:?}", terminal.backend().buffer()).hash(&mut hasher);
        let test_snapshot_hash = format!("{:016x}", hasher.finish());
        rows.push(BenchRow {
            width,
            height,
            messages: snapshot.state.messages.len(),
            workspace_rows: snapshot.state.workspace_rows.len(),
            cold_ansi_ms,
            warm_ansi_ms,
            changed_ansi_ms,
            cold_ansi_bytes: cold_ansi_bytes / iterations,
            warm_ansi_bytes: warm_ansi_bytes / iterations,
            changed_ansi_bytes: changed_ansi_bytes / iterations,
            cold_test_ms,
            warm_test_ms,
            changed_test_ms,
            test_snapshot_hash,
            projection_included: true,
            transport_included: false,
            iterations,
        });
    }
    println!("{}", serde_json::to_string_pretty(&rows)?);
    Ok(())
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct FrameReceipt<'a> {
    v: u8,
    r#type: &'static str,
    epoch: u64,
    scope: &'a str,
    render_micros: u128,
    ansi_bytes: usize,
    width: u16,
    height: u16,
}

fn bridge_benchmark_io<R: BufRead, W: Write>(
    mut reader: R,
    mut output: W,
    width: u16,
    height: u16,
) -> Result<(), Box<dyn std::error::Error>> {
    if !(40..=400).contains(&width) || !(10..=160).contains(&height) {
        return Err("invalid benchmark dimensions".into());
    }
    let counter = Arc::new(AtomicUsize::new(0));
    let mut terminal = Terminal::with_options(
        CrosstermBackend::new(CountingWriter(counter.clone())),
        TerminalOptions {
            viewport: Viewport::Fixed(Rect::new(0, 0, width, height)),
        },
    )?;
    let mut ui: Option<Ui> = None;
    loop {
        let bytes = match read_frame(&mut reader) {
            Ok(Some(bytes)) => bytes,
            Ok(None) => break,
            Err(error) if error.kind() == io::ErrorKind::InvalidData => continue,
            Err(error) => return Err(error.into()),
        };
        let Ok(snapshot) = serde_json::from_slice::<Snapshot>(&bytes) else {
            continue;
        };
        if snapshot.validate().is_err() {
            continue;
        }
        if let Some(current) = &mut ui {
            if !current.update(snapshot) {
                continue;
            }
        } else {
            ui = Some(Ui::new(snapshot));
        }
        let current = ui.as_mut().expect("initialized above");
        let before = counter.load(Ordering::Relaxed);
        let start = Instant::now();
        terminal.draw(|frame| ui::draw(frame, current))?;
        let receipt = FrameReceipt {
            v: 1,
            r#type: "frame",
            epoch: current.snapshot.epoch,
            scope: &current.snapshot.scope,
            render_micros: start.elapsed().as_micros(),
            ansi_bytes: counter.load(Ordering::Relaxed) - before,
            width,
            height,
        };
        serde_json::to_writer(&mut output, &receipt)?;
        output.write_all(b"\n")?;
        output.flush()?;
    }
    Ok(())
}

fn bridge_benchmark(width: u16, height: u16) -> Result<(), Box<dyn std::error::Error>> {
    let input = unsafe { File::from_raw_fd(3) };
    let output = unsafe { File::from_raw_fd(4) };
    bridge_benchmark_io(BufReader::new(input), output, width, height)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    match args.as_slice() {
        [_, mode] if mode == "--bridge" => bridge(),
        [_, mode, width, height] if mode == "--bridge-benchmark" => {
            bridge_benchmark(width.parse()?, height.parse()?)
        }
        [_, mode, path] if mode == "--fixture" => run(load_snapshot(Path::new(path))?, None, None),
        [_, mode, path] if mode == "--benchmark" => benchmark(load_snapshot(Path::new(path))?),
        _ => {
            eprintln!(
                "usage: openmates-tui-prototype --bridge | --bridge-benchmark WIDTH HEIGHT | --fixture SNAPSHOT.json | --benchmark SNAPSHOT.json"
            );
            std::process::exit(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn headless_bridge_acknowledges_only_advancing_frames() {
        let first: Snapshot = serde_json::from_str(include_str!("../fixtures/demo.json")).unwrap();
        let mut second = first.clone();
        second.epoch += 1;
        second.state.draft = "changed".into();
        let mut same_epoch_new_scope = second.clone();
        same_epoch_new_scope.scope = "stale-other-scope".into();
        let frames = [first, second, same_epoch_new_scope]
            .iter()
            .map(|s| serde_json::to_string(s).unwrap())
            .collect::<Vec<_>>()
            .join("\n")
            + "\n";
        let mut output = Vec::new();
        bridge_benchmark_io(Cursor::new(frames), &mut output, 160, 50).unwrap();
        let receipts: Vec<serde_json::Value> = output
            .split(|b| *b == b'\n')
            .filter(|line| !line.is_empty())
            .map(|line| serde_json::from_slice(line).unwrap())
            .collect();
        assert_eq!(receipts.len(), 2);
        assert_eq!(receipts[0]["type"], "frame");
        assert_eq!(receipts[1]["epoch"], 2);
        assert!(receipts[0]["ansiBytes"].as_u64().unwrap() > 0);
    }
}
