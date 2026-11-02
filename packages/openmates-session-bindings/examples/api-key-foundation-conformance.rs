//! Fixed genuine API-key public/opaque conformance consumer; isolated CI only.
use _native::{ApiKeyBridge,ApiKeyOutput,BindingError};
use serde_json::{Value,json};
use std::{io::{Read,Write},net::TcpStream,sync::Arc,time::{Duration,Instant}};
fn ok<T>(value:Result<T,BindingError>)->T{match value{Ok(value)=>value,Err(_)=>panic!("binding failed")}}
fn control(endpoint:&str,path:&str)->Value{
    let address=endpoint.strip_prefix("http://").expect("loopback scheme");
    assert!(address.starts_with("127.0.0.1:"));
    let mut socket=TcpStream::connect(address).expect("control connect");
    socket.set_read_timeout(Some(Duration::from_secs(5))).expect("control deadline");
    write!(socket,"GET {path} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n").expect("control write");
    let mut bytes=String::new();socket.read_to_string(&mut bytes).expect("control read");
    serde_json::from_str(bytes.split_once("\r\n\r\n").expect("control response").1).expect("control JSON")
}
async fn wait_post(endpoint:&str){let deadline=Instant::now()+Duration::from_secs(10);loop{if control(endpoint,"/__test/status")["skill_posts"]==1{return;}assert!(Instant::now()<deadline,"actual POST not observed");tokio::task::yield_now().await;}}
fn decode(output:ApiKeyOutput)->Result<Value,BindingError>{output.encode_with(|text|serde_json::from_str(text).map_err(|_|openmates_sdk::Error::Protocol.into()))}
#[tokio::main]
async fn main(){
    let args=std::env::args().skip(1).collect::<Vec<_>>();assert_eq!(args.len(),3);
    let suite:Value=serde_json::from_str(&std::fs::read_to_string(&args[0]).expect("fixture read")).expect("fixture JSON");
    let suite=&suite["capabilities"]["sdk.configuration"];
    let id=&args[1];let endpoint=&args[2];let v=suite["vectors"].as_array().expect("vectors").iter().find(|v|v["id"]==*id).expect("vector");
    let options=json!({"api_key":suite["account"]["api_key"],"api_url":endpoint,"device_id":suite["account"]["device_id"],"app_url":endpoint,"enhanced_privacy":false,"allow_private_operations":true}).to_string();
    let bridge=ok(ApiKeyBridge::new(&options));let mode=v["mode"].as_str().expect("mode");
    let request=Arc::new(ok(bridge.request()));
    let app=suite["request"]["app"].as_str().expect("app").to_owned();let skill=suite["request"]["skill"].as_str().expect("skill").to_owned();let mut input=suite["request"]["input"].clone();
    let result:Result<Value,BindingError>=match mode{
        "account"|"account_auth_refusal"=>request.account_info_prepare().await.and_then(decode),
        "allocation_cancel"|"allocation_close"|"stale_successor"=>{
            let output=ok(request.account_info_prepare().await);
            if mode=="allocation_close"{ok(bridge.close());}else{request.cancel();}
            if mode=="stale_successor"{let b=ok(bridge.request());let next=ok(b.account_info_prepare().await);drop(output);request.cancel();let value=decode(next);b.cancel();value}else{decode(output)}
        }
        "cancel_after_dispatch"|"concurrent_account"=>{
            let call=request.clone();let pending=tokio::spawn(async move{call.run_skill_prepare(app,skill,input.to_string()).await});
            wait_post(endpoint).await;
            let b=if mode=="concurrent_account"{let next=ok(bridge.request());Some(tokio::time::timeout(Duration::from_secs(5),next.account_info_prepare()).await.expect("B serialized behind held A").and_then(decode))}else{None};
            request.cancel();control(endpoint,"/__test/release");
            let a=pending.await.expect("actual driver join");assert_eq!(a.err().map(|e|e.code),Some("cancelled"));
            b.unwrap_or_else(||Err(openmates_sdk::Error::Cancelled.into()))
        }
        "parallel_code_success"|"parallel_code_failed_status"|"parallel_code_http_failure"=>{
            let code=&v["request"];let app=code["app"].as_str().expect("code app").to_owned();let skill=code["skill"].as_str().expect("code skill").to_owned();let input=code["input"].to_string();
            let call=request.clone();let pending=tokio::spawn(async move{call.run_skill_prepare(app,skill,input).await});
            let deadline=Instant::now()+Duration::from_secs(10);
            loop{let status=control(endpoint,"/__test/status");if status["code_all_arrived"]==true&&status["code_b_sent"]==true{assert_eq!(status["a_released"],false);break;}assert!(Instant::now()<deadline,"code statuses serialized behind A");tokio::task::yield_now().await;}
            if mode=="parallel_code_http_failure"{
                let terminal=tokio::time::timeout(Duration::from_secs(5),pending).await.expect("HTTP failure serialized behind A").expect("actual code driver join");
                let failure=match terminal{Err(error)=>error,Ok(_)=>panic!("code HTTP failure returned a value")};assert_eq!(failure.code,"forbidden");
                assert_eq!(control(endpoint,"/__test/code-terminal")["terminal_while_a_held"],true);control(endpoint,"/__test/release");Err(failure)
            }else{control(endpoint,"/__test/release");pending.await.expect("actual code driver join").and_then(decode)}
        }
        "parallel_tasks_success"|"parallel_tasks_failure"=>{
            let call=request.clone();let pending=tokio::spawn(async move{call.run_skill_prepare(app,skill,input.to_string()).await});
            let deadline=Instant::now()+Duration::from_secs(10);
            loop{
                let status=control(endpoint,"/__test/status");
                if status["parallel_all_arrived"]==true && status["parallel_b_sent"]==true{assert_eq!(status["a_released"],false);break;}
                assert!(Instant::now()<deadline,"original task polls serialized behind held A");tokio::task::yield_now().await;
            }
            if mode=="parallel_tasks_failure"{
                let terminal=tokio::time::timeout(Duration::from_secs(5),pending).await.expect("failure serialized behind held A").expect("actual driver join");
                let failure=match terminal{Err(error)=>error,Ok(_)=>panic!("B failure returned a value")};assert_eq!(failure.code,"invalid_argument");
                assert_eq!(control(endpoint,"/__test/parallel-terminal")["terminal_while_a_held"],true);
                control(endpoint,"/__test/release");Err(failure)
            }else{
                control(endpoint,"/__test/release");pending.await.expect("actual driver join").and_then(decode)
            }
        }
        _=>{
            if mode=="pre_cancel"{request.cancel();}
            if mode=="routing_override"{input["model"]=Value::Null;}
            request.run_skill_prepare(app,skill,input.to_string()).await.and_then(decode)
        }
    };
    ok(bridge.close());
    let output=match result{Ok(value)=>json!({"id":id,"adapter":"actual-rust-api-key-library","value":value}),Err(error)=>json!({"id":id,"adapter":"actual-rust-api-key-library","error":error.code})};
    println!("{output}");
}
