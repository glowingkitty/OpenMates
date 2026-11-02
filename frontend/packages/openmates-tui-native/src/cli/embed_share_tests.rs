//! Focused native option/output/negative command tests, AUTHORED UNRUN.
//! All formatter URLs below are synthetic; none proves runtime share success.
//! Old real executable API-key refusal remains unchanged and required.
//! Actual authenticated binary/backend/cache lifecycle acceptance is separate.
//! These tests exercise production parser and formatter, not copied expected code.
use super::*;
use serde_json::json;
fn invocation()->Invocation{Invocation{path:vec!["embeds".into(),"share".into()],positionals:vec!["33333333".into()],flags:Default::default()}}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn signed_decimal_prefix_and_utf16_password_policy(){
    for(raw,want)in[(" +3600suffix",3600),("-60seconds",-60),("2.9",2),("002",2),("0x10",0),("\u{feff}+2",2),("-0",0)]{
        let mut i=invocation();i.flags.insert("expires".into(),json!(raw));assert_eq!(parse(&i).unwrap_or_else(|_| panic!("synthetic embed-share operation failed")).expires,want);
    }
    for raw in ["NaN","", "Infinity","9007199254740992"]{let mut i=invocation();i.flags.insert("expires".into(),json!(raw));assert!(matches!(parse(&i),Err(CliError::Unsupported{..})));}
    let mut i=invocation();i.flags.insert("password".into(),json!("😀".repeat(5)));assert!(parse(&i).is_ok());
    i.flags.insert("password".into(),json!("😀".repeat(6)));let out=preflight(&i).unwrap_or_else(|| panic!("synthetic embed-share preflight missing")).unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));assert_eq!(out.stderr,"Password must be at most 10 characters.\n");assert!(out.stdout.is_empty());assert_eq!(out.exit_code,1);
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn exact_json_uses_caller_selector_and_human_duration_style(){
    let mut i=invocation();i.flags.insert("expires".into(),json!("3600"));i.flags.insert("password".into(),json!("private"));
    let parsed=parse(&i).unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));let out=output(&i,&parsed,"https://app.invalid/share/embed/canonical#key=synthetic").unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));
    assert_eq!(out.stdout,"\n\x1b[1mEmbed share link\x1b[0m\nhttps://app.invalid/share/embed/canonical#key=synthetic\n\n\x1b[2mExpires in 1 hour(s)\x1b[0m\n\x1b[2mPassword protected\x1b[0m\n");assert!(out.stderr.is_empty());assert_eq!(out.exit_code,0);
    i.flags.insert("json".into(),json!(true));let parsed=parse(&i).unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));let out=output(&i,&parsed,"https://app.invalid/#key=synthetic").unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));
    assert_eq!(serde_json::from_str::<serde_json::Value>(&out.stdout).unwrap(),json!({"url":"https://app.invalid/#key=synthetic","embed_id":"33333333","expires":3600,"password_protected":true}));assert!(!out.stdout.contains("private"));
    for(n,want)in[(29,"0 minute(s)"),(30,"1 minute(s)"),(3599,"60 minute(s)"),(86399,"24 hour(s)"),(86400,"1 day(s)")]{assert_eq!(duration(n),want);}
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,auth.session.isolation
#[test]
fn missing_id_team_unknown_and_repeated_flags_never_reach_client(){
    let mut i=invocation();i.positionals.clear();let out=preflight(&i).unwrap_or_else(|| panic!("synthetic embed-share preflight missing")).unwrap_or_else(|_| panic!("synthetic embed-share operation failed"));assert_eq!(out.exit_code,1);assert!(out.stdout.is_empty());assert_eq!(out.stderr,"Missing embed ID. Usage: openmates embeds share <embed-id>\n");
    for(name,value)in[("team",json!("11111111-1111-4111-8111-111111111111")),("unreviewed",json!(true)),("expires",json!(["1","2"]))]{let mut i=invocation();i.flags.insert(name.into(),value);assert!(parse(&i).is_err());}
}
// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.surface.semantic-parity
#[test]
fn actual_declared_cli_grammar_selects_share_without_foreign_runtime(){
    let parsed=super::super::parse_from(["openmates","embeds","share","33333333","--expires","+3600suffix","--password","secret","--json"]).unwrap();
    let i=parsed.invocation.unwrap();assert_eq!(i.command_path(),"embeds share");assert_eq!(parse(&i).unwrap_or_else(|_| panic!("synthetic embed-share operation failed")).expires,3600);assert!(super::super::execute_public(&i).is_none());
    // Sharing must remain outside the API-key embed capability family.
    assert!(!super::super::sdk_embeds_supported(&i));
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
#[test]
fn expiry_uses_ecmascript_trimstring_not_rust_unicode_whitespace(){
    for code in [0x0009,0x000a,0x000b,0x000c,0x000d,0x0020,0x00a0,0x1680,0x2000,0x2001,0x2002,0x2003,0x2004,0x2005,0x2006,0x2007,0x2008,0x2009,0x200a,0x2028,0x2029,0x202f,0x205f,0x3000,0xfeff]{
        let c=char::from_u32(code).unwrap();let mut i=invocation();i.flags.insert("expires".into(),json!(format!("{c}+60suffix")));assert_eq!(parse(&i).unwrap_or_else(|_| panic!("synthetic embed-share operation failed")).expires,60);
    }
    for code in [0x0085,0x180e,0x200b,0x2060]{let c=char::from_u32(code).unwrap();let mut i=invocation();i.flags.insert("expires".into(),json!(format!("{c}60")));assert!(matches!(parse(&i),Err(CliError::Unsupported{..})));}
}
