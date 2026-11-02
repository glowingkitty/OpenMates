//! Native Personal Cookie embed-share adapter over original ordered sync DATA.
//! The shared Client owns cache decisions, fresh owner admission and encryption.
//! No API-key substitute, process bridge, sorted-ID inference or extra sync.
//! Parsed passwords and pending URL/output remain wiping until publication.
//! Native runtime retains its authenticated store and final output fence.
//! Old-cache, ambiguous expiry and unrepresented scopes fail explicitly.
use super::{CliError,CliOutput,Invocation};
use crate::{client::Client,error::Error};
use serde::Serialize;
use tokio_util::sync::CancellationToken;
use zeroize::{Zeroize,Zeroizing};

struct ShareOptions<'a>{selector:&'a str,expires:i64,password:Zeroizing<String>}
fn unsupported(i:&Invocation,reason:&str)->CliError{CliError::Unsupported{command:i.command_path(),reason:reason.into()}}
fn argument(message:&str)->CliError{CliError::Contract{code:"command_failed",message:message.into()}}
// Match finite safe JS parseInt(value,10) including sign and decimal prefix.
// NaN and rounded unsafe JS integers need a distinct shared wire representation.
fn js_trim_space(c:char)->bool{
    matches!(c,'\u{0009}'..='\u{000d}'|'\u{0020}'|'\u{00a0}'|'\u{1680}'|'\u{2000}'..='\u{200a}'|'\u{2028}'|'\u{2029}'|'\u{202f}'|'\u{205f}'|'\u{3000}'|'\u{feff}')
}
fn expiry(i:&Invocation)->Result<i64,CliError>{
    let Some(raw)=i.text("expires") else{return Ok(0)};
    let raw=raw.trim_start_matches(js_trim_space);
    let (negative,digits)=if let Some(v)=raw.strip_prefix('-'){(true,v)}else{(false,raw.strip_prefix('+').unwrap_or(raw))};
    let count=digits.bytes().take_while(u8::is_ascii_digit).count();
    let number=digits[..count].parse::<u64>().ok().filter(|n|*n<=9_007_199_254_740_991)
        .ok_or_else(||unsupported(i,"NaN and unsafe rounded expiry values are not represented by the shared signed-duration API."))?;
    Ok(if negative{-(number as i64)}else{number as i64})
}
fn parse(i:&Invocation)->Result<ShareOptions<'_>,CliError>{
    super::handlers::flags(i,&["expires","password","personal","team"])?;
    let selector=i.positionals.first().map(String::as_str).filter(|s|!s.is_empty())
        .ok_or_else(||argument("Missing embed ID. Usage: openmates embeds share <embed-id>"))?;
    if i.has("team"){return Err(unsupported(i,"Team embed sharing is not supported by the Personal saved-read operation."))}
    let expires=expiry(i)?;
    let password=Zeroizing::new(i.text("password").unwrap_or("").to_owned());
    if password.encode_utf16().count()>10{return Err(argument("Password must be at most 10 characters."))}
    Ok(ShareOptions{selector,expires,password})
}
pub(super) fn preflight(i:&Invocation)->Option<Result<CliOutput,CliError>>{
    match parse(i) {
        Ok(_)=>None,
        Err(CliError::Contract{message,..})=>Some(Ok(CliOutput{stdout:String::new(),stderr:format!("{message}\n"),exit_code:1})),
        Err(error)=>Some(Err(error)),
    }
}
fn duration(seconds:i64)->String{
    // Positive integer durations only; TS Math.round(x) == floor(x+0.5).
    let (unit,label)=if seconds<3600{(60,"minute(s)")}else if seconds<86400{(3600,"hour(s)")}else{(86400,"day(s)")};
    format!("{} {label}",seconds/unit+ i64::from(seconds%unit>=unit/2))
}
#[derive(Serialize)]
struct ShareJson<'a>{url:&'a str,embed_id:&'a str,expires:i64,password_protected:bool}
fn output(i:&Invocation,options:&ShareOptions<'_>,url:&str)->Result<CliOutput,CliError>{
    let mut stdout=if i.boolean("json"){
        let value=ShareJson{url,embed_id:options.selector,expires:options.expires,password_protected:!options.password.is_empty()};
        let mut serialized=Zeroizing::new(serde_json::to_string_pretty(&value).map_err(|_|Error::Protocol)?);serialized.push('\n');serialized
    }else{
        let mut text=Zeroizing::new(format!("\n\x1b[1mEmbed share link\x1b[0m\n{url}\n\n"));
        if options.expires>0{text.push_str(&format!("\x1b[2mExpires in {}\x1b[0m\n",duration(options.expires)));}
        if !options.password.is_empty(){text.push_str("\x1b[2mPassword protected\x1b[0m\n");}text
    };
    Ok(CliOutput{stdout:std::mem::take(&mut *stdout),stderr:String::new(),exit_code:0})
}
pub(super) async fn execute(i:&Invocation,client:&mut Client,cancel:CancellationToken)->Result<CliOutput,CliError>{
    execute_admitted(i,client,cancel).await.map(|(output,_)|output)
}
/// Native application retains the SAME fresh read through its final store fence.
/// No public constructor, imported key/status or replacement read is accepted.
pub async fn execute_admitted(i:&Invocation,client:&mut Client,cancel:CancellationToken)->Result<(CliOutput,openmates_sdk::client::saved_embed::SavedEmbedRead),CliError>{
    let options=parse(i)?;
    if cancel.is_cancelled(){return Err(Error::Cancelled.into())}
    // Explicit --personal is allowed only when the genuine current profile is
    // already Personal. Never clear/restore a Team merely to admit this slice.
    if client.session().is_none_or(|s|s.active_team_id.is_some()){return Err(unsupported(i,"A genuine Personal Cookie profile is required; no Team or API-key substitution."))}
    client.set_operation_cancel(cancel.clone());
    client.ensure_saved_embed_selector().await?;
    let read=client.saved_embed_selector(options.selector).await?;
    let url=read.share_url(client,options.expires,&options.password)?;
    let mut result=output(i,&options,&url)?;
    if let Err(error)=read.check(client).and_then(|()|if cancel.is_cancelled(){Err(Error::Cancelled)}else{Ok(())}){
        result.stdout.zeroize();result.stderr.zeroize();return Err(error.into());
    }
    Ok((result,read))
}
#[cfg(test)]
#[path="embed_share_tests.rs"]
mod tests;
