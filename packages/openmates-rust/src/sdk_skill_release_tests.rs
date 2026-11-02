//! Direct public Core HTTP tests. Actual loopback/body holds; authored UNRUN.
use super::*;
use std::sync::{Arc,atomic::{AtomicBool,AtomicUsize,Ordering}};
use tokio::{io::{AsyncReadExt,AsyncWriteExt},net::{TcpListener,TcpStream},sync::oneshot};
#[derive(Clone,Copy)]
enum Wire {Sync,Poll,Account}
#[derive(Clone,Copy)]
enum Stop {None,Caller,Operation,GateCaller,GateOperation}
fn ok<T>(result:Result<T>)->T{match result{Ok(value)=>value,Err(_)=>panic!("Core operation failed")}}
async fn request(socket:&mut TcpStream)->(String,Value){
    let mut bytes=Vec::new();let end=loop{let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("HTTP request bytes");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<=65536);if let Some(at)=bytes.windows(4).position(|part|part==b"\r\n\r\n"){break at+4;}};
    let head=std::str::from_utf8(&bytes[..end]).expect("HTTP headers");
    assert!(head.lines().any(|line|line.eq_ignore_ascii_case("authorization: Bearer sk-api-fixture")),"explicit bearer without local setup suffix");
    assert!(!head.to_ascii_lowercase().contains("cookie:"),"no Cookie SDK substitution");
    let method_path=head.lines().next().expect("request line").split_whitespace().take(2).collect::<Vec<_>>().join(" ");
    let length=head.lines().find_map(|line|line.split_once(':').filter(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().expect("content length"))).unwrap_or(0);
    assert!(length<=1024*1024);
    while bytes.len()<end+length{let mut chunk=[0;1024];let n=socket.read(&mut chunk).await.expect("HTTP body bytes");assert!(n>0);bytes.extend_from_slice(&chunk[..n]);}
    let body=if length==0{Value::Null}else{serde_json::from_slice(&bytes[end..end+length]).expect("explicit input JSON")};
    (method_path,body)
}
async fn response_headers(socket:&mut TcpStream,value:&Value)->Vec<u8>{
    let raw=serde_json::to_vec(value).expect("synthetic JSON");
    socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await.expect("actual response headers");socket.flush().await.expect("response header flush");raw
}
async fn case(wire:Wire,stop:Stop,generated:bool){
    let listener=TcpListener::bind("127.0.0.1:0").await.expect("loopback bind");let endpoint=format!("http://{}",listener.local_addr().expect("address"));
    let(entered,held)=oneshot::channel();let(release,continue_body)=oneshot::channel();let posts=Arc::new(AtomicUsize::new(0));let polls=Arc::new(AtomicUsize::new(0));let p=posts.clone();let reads=polls.clone();
    let expected=match wire{Wire::Account=>json!({"id":"synthetic-owner","ordered":[3,1,2]}),_=>json!({"success":true,"data":{"ordered":[3,1,2],"private":"synthetic-private-result"}})};let result_value=expected.clone();
    let peer=tokio::spawn(async move{
        let(mut socket,_)=listener.accept().await.expect("actual first connection");let(path,body)=request(&mut socket).await;
        let mut payload=result_value;
        if matches!(wire,Wire::Account){assert_eq!(path,"GET /v1/sdk/account");assert!(body.is_null());}
        else{assert_eq!(path,"POST /v1/apps/web/skills/search");assert_eq!(body,json!({"query":"synthetic direct public Core"}));p.fetch_add(1,Ordering::SeqCst);}
        if matches!(wire,Wire::Poll){
            let admitted=json!({"success":true,"data":{"task_id":"original_task"}});let raw=response_headers(&mut socket,&admitted).await;socket.write_all(&raw).await.expect("actual POST body");drop(socket);
            let(next,_)=listener.accept().await.expect("actual final poll connection");socket=next;let(path,body)=request(&mut socket).await;assert_eq!(path,"GET /v1/tasks/original_task");assert!(body.is_null());reads.fetch_add(1,Ordering::SeqCst);
            payload=json!({"status":"completed","result":payload["data"]});
        }
        let raw=response_headers(&mut socket,&payload).await;
        entered.send(()).expect("actual response body held");continue_body.await.expect("release actual held body");
        socket.write_all(&raw).await.expect("actual released body");socket.flush().await.expect("actual body flush");
        assert!(std::future::poll_fn(|cx| std::task::Poll::Ready(listener.poll_accept(cx))).await.is_pending(),"no paid POST replay/extra request");
    });
    let caller=CancellationToken::new();let parent=CancellationToken::new();let fire=Arc::new(AtomicBool::new(false));let gate_fire=fire.clone();let gate_caller=caller.clone();let gate_parent=parent.clone();
    let gate=Arc::new(move||{if gate_fire.load(Ordering::Acquire){match stop{Stop::GateCaller=>gate_caller.cancel(),Stop::GateOperation=>gate_parent.cancel(),_=>{}}}Ok(())});
    let mut sdk=ok(OpenMates::new(SdkOptions{api_url:endpoint.clone(),credentials:SdkCredentials::ApiKey(ok(ApiKey::new("sk-api-fixture.localSuffix"))),device_id:"synthetic-explicit-device".into(),client_options:ClientOptions{app_url:Some(endpoint),private_operation_gate:Some(gate),..ClientOptions::default()}}));
    sdk.set_operation_cancel(parent.clone());let supplied=caller.clone();
    let run=tokio::spawn(async move{
        if matches!(wire,Wire::Account){sdk.account_info().await}
        else if generated{sdk.apps().web().search(json!({"query":"synthetic direct public Core"})).await}
        else{sdk.run_app_skill("web","search",json!({"query":"synthetic direct public Core"}),supplied).await}
    });
    held.await.expect("actual HTTP request and held response body");
    match stop{Stop::None=>{},Stop::Caller=>caller.cancel(),Stop::Operation=>parent.cancel(),Stop::GateCaller|Stop::GateOperation=>fire.store(true,Ordering::Release)}
    release.send(()).expect("release original actual body");let result=run.await.expect("actual public Core join");
    match stop{Stop::None=>assert_eq!(ok(result),expected),_=>assert!(matches!(result,Err(Error::Cancelled)),"original negative token must refuse actual held result")}
    peer.await.expect("actual wire assertions");assert_eq!(posts.load(Ordering::SeqCst),usize::from(!matches!(wire,Wire::Account)));assert_eq!(polls.load(Ordering::SeqCst),usize::from(matches!(wire,Wire::Poll)));
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn public_sync_post_body_cancel_refuses_original_result(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Sync,Stop::Caller,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn public_final_poll_body_cancel_refuses_original_result(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Poll,Stop::Caller,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn public_sync_post_positive_preserves_value_and_single_post(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Sync,Stop::None,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn public_completed_poll_positive_preserves_value_and_order(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Poll,Stop::None,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn final_gate_returning_ok_cannot_hide_supplied_cancel(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Sync,Stop::GateCaller,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn final_poll_gate_returning_ok_cannot_hide_core_cancel(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Poll,Stop::GateOperation,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn account_info_held_body_respects_original_core_cancel(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Account,Stop::Operation,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn account_info_positive_preserves_original_value(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Account,Stop::None,false)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn generated_typed_skill_respects_same_original_core_negative(){tokio::time::timeout(Duration::from_secs(5),case(Wire::Sync,Stop::Operation,true)).await.expect("HTTP watchdog");}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn public_two_plain_task_results_preserve_order_without_nested_results() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("actual loopback bind");
        let endpoint = format!("http://{}", listener.local_addr().expect("address"));
        let first = json!({"name":"first","nested":{"ordered":[3,1,2]}});
        let second = json!({"name":"second","nested":{"ordered":[9,7,8]}});
        let expected = json!({"success":true,"data":{"results":[first.clone(),second.clone()]}});
        let peer = tokio::spawn(async move {
            let mut paths = Vec::new();
            for _ in 0..3 {
                let (mut socket, _) = listener.accept().await.expect("actual HTTP connection");
                let (path, body) = request(&mut socket).await;
                let payload = match path.as_str() {
                    "POST /v1/apps/web/skills/search" => {
                        assert!(paths.is_empty(), "one original POST precedes task reads");
                        assert_eq!(body, json!({"query":"synthetic two plain task results"}));
                        json!({"success":true,"data":{"task_ids":["plain_first","plain_second"]}})
                    }
                    "GET /v1/tasks/plain_first" => {
                        assert!(body.is_null());
                        json!({"status":"completed","result":first.clone()})
                    }
                    "GET /v1/tasks/plain_second" => {
                        assert!(body.is_null());
                        json!({"status":"completed","result":second.clone()})
                    }
                    _ => panic!("unexpected actual task request"),
                };
                paths.push(path);
                let raw = response_headers(&mut socket, &payload).await;
                socket.write_all(&raw).await.expect("actual response body");
                socket.flush().await.expect("actual body flush");
            }
            // Poll arrival order is not an output-order oracle: the successor
            // may poll concurrently, but each exact task must be requested once.
            paths.sort();
            assert_eq!(paths, vec!["GET /v1/tasks/plain_first", "GET /v1/tasks/plain_second", "POST /v1/apps/web/skills/search"]);
            assert!(std::future::poll_fn(|cx| std::task::Poll::Ready(listener.poll_accept(cx))).await.is_pending(), "no extra paid POST or poll");
        });
        let sdk = ok(OpenMates::new(SdkOptions {
            api_url:endpoint.clone(),
            credentials:SdkCredentials::ApiKey(ok(ApiKey::new("sk-api-fixture.localSuffix"))),
            device_id:"synthetic-explicit-device".into(),
            client_options:ClientOptions {app_url:Some(endpoint), ..ClientOptions::default()},
        }));
        let value = ok(sdk.run_app_skill("web", "search", json!({"query":"synthetic two plain task results"}), CancellationToken::new()).await);
        assert_eq!(value, expected, "fallback retains two original plain results in task-id order");
        peer.await.expect("actual peer request assertions");
    }).await.expect("actual HTTP watchdog");
}
