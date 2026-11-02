//! Explicit dev-only real inference proof, never selected by isolated CI.
use openmates::{client::Client, model::StreamUpdate};
use tokio_util::sync::CancellationToken;

#[tokio::test]
#[ignore = "real inference requires a leased dev test account and explicit dev execution"]
async fn native_automatic_inference() {
    assert_ne!(
        std::env::var("CI").as_deref(),
        Ok("true"),
        "real inference never runs in CI"
    );
    assert_eq!(std::env::var("RUST_TUI_LIVE_APPROVED").as_deref(), Ok("1"));
    let api = std::env::var("RUST_TUI_API_URL").unwrap();
    assert_eq!(api, "https://api.dev.openmates.org");
    let email = zeroize::Zeroizing::new(std::env::var("RUST_TUI_EMAIL").unwrap());
    let password = zeroize::Zeroizing::new(std::env::var("RUST_TUI_PASSWORD").unwrap());
    let otp = zeroize::Zeroizing::new(std::env::var("RUST_TUI_TOTP_CODE").unwrap_or_default());
    let mut client = Client::new(&api, None).unwrap();
    client
        .login_password(&email, &password, (!otp.is_empty()).then_some(otp.as_str()))
        .await
        .unwrap();
    let result=async{
        let mut chat_id=None;
        for prompt in [
            "Explain in three short sentences why incremental terminal rendering can improve responsiveness.",
            "Create a tiny Rust code example that formats a refresh-rate counter, and explain one Unicode rendering consideration.",
        ]{
            let (updates,mut receiver)=tokio::sync::mpsc::channel(128);
            let drain=tokio::spawn(async move{
                let mut submitted=false;let mut admitted=false;let mut completed=false;
                while let Some(update)=receiver.recv().await{match update{StreamUpdate::Submitted{..}=>submitted=true,StreamUpdate::Admitted{..}=>admitted=true,StreamUpdate::Completed{..}=>completed=true,StreamUpdate::Consent{..}=>panic!("Synthetic proof must not require private memory consent"),_=>{}}}
                (submitted,admitted,completed)
            });
            let chat=tokio::time::timeout(std::time::Duration::from_secs(600),client.send_message(chat_id.as_deref(),prompt,updates,CancellationToken::new())).await.map_err(|_|"turn timeout")?.map_err(|_|"native turn failed")?;
            let (submitted,admitted,completed)=drain.await.map_err(|_|"stream collector failed")?;
            if !(submitted&&admitted&&completed){return Err("missing durable delivery lifecycle")}
            if !chat.messages.iter().any(|message|message.role=="assistant"&&!message.content.trim().is_empty()){return Err("empty assistant response")}
            let canonical=client.open_chat(&chat.id).await.map_err(|_|"canonical reread failed")?;
            let latest=chat.messages.last().ok_or("missing final message")?;
            if !canonical.messages.iter().any(|message|message.id==latest.id&&message.content==latest.content){return Err("canonical encrypted response mismatch")}
            chat_id=Some(chat.id);
        }
        println!("Native automatic-routing proof passed: two turns, durable admission, response persistence and canonical reread; chat_id={}",chat_id.unwrap());
        Ok::<(),&'static str>(())
    }.await;
    let logged_out = client.logout().await;
    result.unwrap();
    logged_out.unwrap();
}
