//! Genuine native code-job HTTP barriers; authored UNRUN for isolated CI.
use super::*;
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
use tokio::{io::{AsyncReadExt,AsyncWriteExt},sync::{mpsc,oneshot}};
async fn request(stream:&mut tokio::net::TcpStream)->(String,Value){
    let mut bytes=vec![];let(end,length)=loop{let mut chunk=[0u8;2048];let n=stream.read(&mut chunk).await.unwrap();assert!(n>0);bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<65536);
        if let Some(end)=bytes.windows(4).position(|v|v==b"\r\n\r\n"){let header=String::from_utf8_lossy(&bytes[..end]);let length=header.lines().find_map(|line|{let(k,v)=line.split_once(':')?;k.eq_ignore_ascii_case("content-length").then(||v.trim().parse::<usize>().unwrap())}).unwrap_or(0);break(end+4,length);}};
    while bytes.len()<end+length{let mut chunk=[0u8;2048];let n=stream.read(&mut chunk).await.unwrap();assert!(n>0);bytes.extend_from_slice(&chunk[..n]);assert!(bytes.len()<65536);}
    (String::from_utf8_lossy(&bytes[..end]).into_owned(),if length==0{Value::Null}else{serde_json::from_slice(&bytes[end..end+length]).unwrap()})
}
async fn headers(stream:&mut tokio::net::TcpStream,status:u16,body:&Value)->Vec<u8>{
    let bytes=serde_json::to_vec(body).unwrap();stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",bytes.len()).as_bytes()).await.unwrap();stream.flush().await.unwrap();bytes
}
async fn complete(stream:&mut tokio::net::TcpStream,body:&Value)->std::io::Result<()>{
    let raw=serde_json::to_vec(body).unwrap();stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await?;stream.write_all(&raw).await
}
fn input()->Value{let run=json!({"mode":"direct","entry_path":"main.py","files":[{"path":"main.py","content_base64":"cHJpbnQoJ3N5bnRoZXRpYyBjb2RlIGZpeHR1cmUnKQo=","language":"python","is_target":true}],"enable_internet":false});json!({"requests":vec![run;5]})}
fn status(index:usize,failed:bool)->Value{json!({"run_id":format!("run-{index}"),"status":if failed{"failed"}else{"finished"},"exit_code":if failed{1}else{0}})}
fn initial(count:usize)->Value{
    let mut values=(0..count).map(|i|json!({"status_path":format!("/v1/code/run/run-{i}"),"label":i})).collect::<Vec<_>>();
    values.insert(1,json!({"kept":"no status path"}));values.insert(2,json!(7));
    json!({"success":true,"credits_charged":count,"data":{"batch":"code-fixture","results":values}})
}
fn sdk(base:&str,gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>)->OpenMates{
    OpenMates::new(SdkOptions{api_url:base.into(),credentials:SdkCredentials::ApiKey(ApiKey::new("sk-api-codeFixture.localSetupSuffix").unwrap()),device_id:"code-fixture-device".into(),client_options:ClientOptions{app_url:Some(base.into()),private_operation_gate:gate,..ClientOptions::default()}}).unwrap()
}
async fn case(mode:u8){
    let count=5usize;let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let(all_tx,all_rx)=oneshot::channel();let(release_tx,release_rx)=oneshot::channel();let(parsed_tx,mut parsed_rx)=mpsc::unbounded_channel();
    let sent=Arc::new(AtomicBool::new(false));let released=Arc::new(AtomicBool::new(false));let deny=Arc::new(AtomicBool::new(false));
    let gate_sent=sent.clone();let gate_released=released.clone();let gate_deny=deny.clone();
    let gate:Arc<dyn Fn()->Result<()>+Send+Sync>=Arc::new(move||{if gate_deny.load(Ordering::Acquire){return Err(Error::Forbidden)}if gate_sent.load(Ordering::Acquire)&&!gate_released.load(Ordering::Acquire){let _=parsed_tx.send(());}Ok(())});
    let peer_sent=sent.clone();let peer_released=released.clone();
    let peer=tokio::spawn(async move{
        let(mut post,_)=listener.accept().await.unwrap();let mut trace=vec![request(&mut post).await];assert!(trace[0].0.starts_with("POST /v1/apps/code/skills/run "));assert_eq!(trace[0].1,input());
        let response=initial(count);let raw=headers(&mut post,200,&response).await;post.write_all(&raw).await.unwrap();drop(post);
        let mut slots=(0..count).map(|_|None).collect::<Vec<Option<tokio::net::TcpStream>>>();
        // No response before all five GETs: serial/max3 cannot pass the barrier.
        for _ in 0..count{let(mut stream,_)=listener.accept().await.unwrap();let seen=request(&mut stream).await;
            let path=seen.0.lines().next().unwrap().split_whitespace().nth(1).unwrap();let index=path.strip_prefix("/v1/code/run/run-").unwrap().parse::<usize>().unwrap();assert!(index<count);assert!(slots[index].replace(stream).is_none());trace.push(seen);}
        let mut a=slots[0].take().unwrap();let a_body=headers(&mut a,200,&status(0,false)).await;
        all_tx.send(()).unwrap();
        // Only B can complete before release. All request gates already ran;
        // A has real headers but no body, all other bodies are held as well.
        peer_sent.store(true,Ordering::Release);let mut b=slots[1].take().unwrap();
        let body=if mode==2{json!({"detail":"synthetic-private-server-diagnostic"})}else{status(1,mode==1)};
        let raw=headers(&mut b,if mode==2{403}else{200},&body).await;b.write_all(&raw).await.unwrap();drop(b);
        release_rx.await.unwrap();peer_released.store(true,Ordering::Release);
        for(index,stream)in slots.into_iter().enumerate(){if let Some(mut stream)=stream{let written=complete(&mut stream,&status(index,false)).await;if mode<=1{written.unwrap();}}}
        let write=a.write_all(&a_body).await;if mode<=1{write.unwrap();}
        trace
    });
    let sdk=sdk(&base,Some(gate));let caller=CancellationToken::new();let original=sdk.operation_cancel.clone();
    if mode==2{
        let result=sdk.run_app_skill("code","run",input(),caller.clone()).await;assert_eq!(result,Err(Error::Forbidden));all_rx.await.unwrap();
        assert!(!released.load(Ordering::Acquire),"actual B HTTP failure reached caller before A body release");release_tx.send(()).unwrap();
    }else{
        let call=sdk.run_app_skill("code","run",input(),caller.clone());
        let control=async{all_rx.await.unwrap();parsed_rx.recv().await.unwrap();assert!(!released.load(Ordering::Acquire),"actual B parsed/core policy callback while A held");
            match mode{0|1=>{},3=>caller.cancel(),4=>original.cancel(),5=>deny.store(true,Ordering::Release),_=>unreachable!()}release_tx.send(()).unwrap();};
        let(result,())=tokio::join!(call,control);
        match mode{0|1=>{let value=result.unwrap();assert_eq!(value["data"]["batch"],"code-fixture");assert_eq!(value["credits_charged"],count);let rows=value["data"]["results"].as_array().unwrap();assert_eq!(rows.len(),count+2);
            assert_eq!(rows[1],json!({"kept":"no status path"}));assert_eq!(rows[2],json!(7));
            for i in 0..count{let at=if i==0{0}else{i+2};assert_eq!(rows[at]["label"],i);assert_eq!(rows[at]["status_path"],format!("/v1/code/run/run-{i}"));assert_eq!(rows[at]["final"],status(i,mode==1&&i==1));}},
            3|4=>assert_eq!(result,Err(Error::Cancelled)),5=>assert_eq!(result,Err(Error::Forbidden)),_=>unreachable!()}
    }
    let trace=peer.await.unwrap();assert_eq!(trace.len(),count+1);assert_eq!(trace.iter().filter(|(h,_)|h.starts_with("POST /v1/apps/code/skills/run ")).count(),1);
    for i in 0..count{assert_eq!(trace.iter().filter(|(h,_)|h.starts_with(&format!("GET /v1/code/run/run-{i} "))).count(),1);}
    for(header,_)in trace{let h=header.to_lowercase();assert!(h.contains("authorization: bearer sk-api-codefixture"));assert!(h.contains("x-openmates-device-identity: code-fixture-device"));assert!(!h.contains("localsetupsuffix"));assert!(!h.contains("cookie:"));}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn all_original_code_paths_start_and_b_finished_or_failed_data_parses_before_a_release(){
    for mode in [0,1]{tokio::time::timeout(Duration::from_secs(15),case(mode)).await.expect("deadlock watchdog only");}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn original_code_b_http_failure_returns_safely_before_a_release_without_paid_retry(){
    tokio::time::timeout(Duration::from_secs(15),case(2)).await.expect("deadlock watchdog only");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn original_code_pending_and_completed_results_refuse_caller_core_cancel_and_policy_denial(){
    for mode in [3,4,5]{tokio::time::timeout(Duration::from_secs(15),case(mode)).await.expect("deadlock watchdog only");}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.surface.semantic-parity
#[tokio::test]
async fn original_code_path_count_guards_and_unresolved_entries_stay_unchanged(){
    for (rows,reject) in [(vec![],false),(vec![json!(7),json!({"kept":"no path"}),Value::Null],false),(vec![json!({"status_path":"/not-code/original"})],true),(vec![json!({"status_path":"/v1/code/run/original"});101],true)]{
        let expected=json!({"success":true,"data":{"results":rows}});let(base,peer)=super::tests::server(vec![(200,expected.clone())]).await;
        let result=sdk(&base,None).run_app_skill("code","run",input(),CancellationToken::new()).await;
        if reject{assert_eq!(result,Err(Error::Protocol));}else{assert_eq!(result,Ok(expected));}
        let trace=peer.await.unwrap();assert_eq!(trace.len(),1);assert!(trace[0].0.starts_with("POST /v1/apps/code/skills/run "));
    }
}
