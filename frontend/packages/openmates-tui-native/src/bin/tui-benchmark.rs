//! Offline real-renderer benchmark. Raw fixtures are parsed independently of TypeScript.
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use openmates::{
    model::{Chat, Item, Workspace},
    ui::Ui,
};
use ratatui::{Terminal, backend::CrosstermBackend, layout::Rect};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    io::{self, Write},
    sync::{Arc, Mutex},
    time::Instant,
};
#[derive(Deserialize)]
struct Fixture {
    chat: Chat,
    tasks: Vec<Item>,
}
#[derive(Clone, Default)]
struct Output(Arc<Mutex<Vec<u8>>>);
impl Write for Output {
    fn write(&mut self, b: &[u8]) -> io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(b);
        Ok(b.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
fn stats(v: &[f64]) -> serde_json::Value {
    let mut s = v.to_vec();
    s.sort_by(f64::total_cmp);
    json!({"medianMs":s[s.len()/2],"p95Ms":s[((s.len() as f64*0.95).ceil() as usize)-1]})
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let args: Vec<String> = std::env::args().collect();
    let opt = |name: &str, default: &str| {
        args.windows(2)
            .find(|v| v[0] == name)
            .map(|v| v[1].clone())
            .unwrap_or(default.into())
    };
    let fixture: Fixture =
        serde_json::from_slice(&std::fs::read(opt("--fixture", "fixture.json"))?)?;
    let width: u16 = opt("--width", "80").parse()?;
    let height: u16 = opt("--height", "24").parse()?;
    let iterations: usize = opt("--iterations", "20").parse()?;
    if iterations < 3 {
        return Err("iterations must be >=3".into());
    }
    let workspace = opt("--workspace", "chat");
    let task_count = fixture.tasks.len();
    let mut ui = Ui::new();
    ui.set_authenticated(true);
    ui.set_username("Synthetic owner");
    ui.set_items(Workspace::Tasks, fixture.tasks);
    ui.set_chat(fixture.chat);
    if workspace == "tasks" {
        ui.key(KeyEvent::new(KeyCode::Char('5'), KeyModifiers::CONTROL));
        ui.key(KeyEvent::new(KeyCode::Tab, KeyModifiers::NONE));
    }
    ui.resize(width, height);
    let output = Output::default();
    let backend = CrosstermBackend::new(output.clone());
    let mut term = Terminal::with_options(
        backend,
        ratatui::TerminalOptions {
            viewport: ratatui::Viewport::Fixed(Rect::new(0, 0, width, height)),
        },
    )?;
    let mut draw = |ui: &mut Ui| -> Result<(f64, usize, String), io::Error> {
        output.0.lock().unwrap().clear();
        let t = Instant::now();
        let completed = term.draw(|f| ui.draw(f))?;
        let ms = t.elapsed().as_secs_f64() * 1000.;
        let screen = completed
            .buffer
            .content
            .iter()
            .map(|c| c.symbol())
            .collect::<String>();
        let bytes = output.0.lock().unwrap().len();
        Ok((ms, bytes, screen))
    };
    let cold = draw(&mut ui)?;
    let startup_ms = started.elapsed().as_secs_f64() * 1000.;
    for _ in 0..3 {
        draw(&mut ui)?;
    }
    let mut draft = vec![];
    let mut scroll = vec![];
    let mut draft_bytes = vec![];
    let mut scroll_bytes = vec![];
    for i in 0..iterations {
        ui.key(KeyEvent::new(KeyCode::Char('u'), KeyModifiers::CONTROL));
        ui.paste(&format!("synthetic draft {i}"));
        let r = draw(&mut ui)?;
        draft.push(r.0);
        draft_bytes.push(r.1);
    }
    if workspace == "tasks" {
        ui.key(KeyEvent::new(KeyCode::Tab, KeyModifiers::NONE));
    }
    let mut selected = 0;
    let mut selection_targets = Vec::new();
    for i in 0..iterations {
        if workspace == "tasks" {
            let target = ((i + 1) * task_count / iterations).min(task_count.saturating_sub(1));
            selection_targets.push(target);
            while selected < target {
                ui.key(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE));
                selected += 1;
            }
        } else {
            ui.key(KeyEvent::new(KeyCode::PageUp, KeyModifiers::NONE));
        }
        let r = draw(&mut ui)?;
        scroll.push(r.0);
        scroll_bytes.push(r.1);
    }
    let last = draw(&mut ui)?;
    println!(
        "{}",
        json!({"backend":"rust","workspace":workspace,"viewport":format!("{width}x{height}"),"coldLayoutAnsiMs":cold.0,"startupInsideProcessMs":startup_ms,"draft":stats(&draft),"scroll":stats(&scroll),"scrollOperation":if workspace=="tasks" {"Identical selected-task targets; selection-follow scroll when the board overflows"}else{"PageUp"},"selectionTargets":selection_targets,"coldAnsiBytes":cold.1,"draftAnsiBytes":draft_bytes,"scrollAnsiBytes":scroll_bytes,"unchangedAnsiBytes":last.1,"screenSha256":format!("{:x}",Sha256::digest(last.2.as_bytes())),"screenText":last.2,"measurement":"Actual UI layout and ANSI emission to memory; excludes real terminal, input scheduling, account sync, crypto and network. Startup excludes OS process launch."})
    );
    Ok(())
}
