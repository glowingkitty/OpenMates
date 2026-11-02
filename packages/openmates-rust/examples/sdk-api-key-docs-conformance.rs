//! Synthetic developer harness only; actual Rust SDK docs methods, no CLI delegation.
// contract-test-file: tooling
use openmates_sdk::{ApiKey,ClientOptions,Error,OpenMates,SdkCredentials,SdkOptions};
use serde_json::{Value,json};
use std::{io::Read,path::PathBuf,process::{Command,ExitCode},time::Instant};
fn field<'a>(v:&'a Value,k:&str)->Result<&'a str,&'static str>{v[k].as_str().ok_or("synthetic field")}
fn code(e:Error)->&'static str{match e{Error::Authentication=>"authentication",Error::Forbidden=>"forbidden",Error::Conflict=>"conflict",Error::Invalid(_)=>"invalid",Error::Offline=>"offline",Error::Cancelled=>"cancelled",_=>"protocol"}}
fn cpu_ticks()->Result<u64,&'static str>{
 let text=std::fs::read_to_string("/proc/self/stat").map_err(|_|"Linux CPU clock")?;
 let fields=text.rsplit_once(") ").ok_or("CPU clock fields")?.1.split_whitespace().collect::<Vec<_>>();
 let user=fields.get(11).ok_or("CPU user")?.parse::<u64>().map_err(|_|"CPU user")?;
 let system=fields.get(12).ok_or("CPU system")?.parse::<u64>().map_err(|_|"CPU system")?;Ok(user+system)
}
async fn run_case()->Result<(),&'static str>{
 let mut bytes=vec![];std::io::stdin().take(1024*1024+1).read_to_end(&mut bytes).map_err(|_|"fixture input")?;
 if bytes.len()>1024*1024{return Err("fixture bound")}
 let c:Value=serde_json::from_slice(&bytes).map_err(|_|"fixture JSON")?;let endpoint=field(&c,"endpoint")?;
 let url=url::Url::parse(endpoint).map_err(|_|"loopback URL")?;
 if url.scheme()!="http"||url.host_str()!=Some("127.0.0.1")||url.port().is_none()||url.path()!="/"||url.query().is_some()||url.fragment().is_some()||!url.username().is_empty()||url.password().is_some(){return Err("loopback endpoint")}
 if field(&c,"api_key")?!="sk-api-docsOwnerA.localSetupSuffix"||field(&c,"device_id")?!="synthetic-docs-device"{return Err("synthetic identity")}
 let v=&c["vector"];let anonymous=v["anonymous"].as_bool().ok_or("anonymous flag")?;
 let credentials=if anonymous{SdkCredentials::Anonymous{anonymous_id:"synthetic-docs-anon".into()}}else{SdkCredentials::ApiKey(ApiKey::new(field(&c,"api_key")?).map_err(|_|"synthetic key")?)};
 let client=OpenMates::new(SdkOptions{api_url:endpoint.into(),credentials,device_id:field(&c,"device_id")?.into(),client_options:ClientOptions::default()}).map_err(|_|"client options")?;
 let iterations=c["iterations"].as_u64().unwrap_or(1);if !matches!(iterations,1|1024){return Err("iteration bound")}
 let before=cpu_ticks()?;let start=Instant::now();let mut result=Ok(Value::Null);
 for _ in 0..iterations{
  result=match field(v,"operation")?{"list"=>client.docs().list().await,"search"=>client.docs().search(field(v,"query")?).await,"show"=>client.docs().show(field(v,"slug")?).await,"download"=>client.docs().download(field(v,"slug")?).await,_=>return Err("docs operation")};
  if result.is_err(){break}
 }
 let ticks=cpu_ticks()?.checked_sub(before).ok_or("CPU monotonic")?;let wall=start.elapsed().as_secs_f64()*1000.0;
 let mut output=match result{Ok(value)=>json!({"ok":true,"value":value}),Err(e)=>json!({"ok":false,"error":code(e)})};
 if iterations>1{output["performance"]=json!({"iterations":iterations,"cpuTicks":ticks,"wallMs":wall});}
 println!("{output}");Ok(())
}
#[tokio::main]
async fn main()->ExitCode{
 let args=std::env::args().skip(1).collect::<Vec<_>>();
 if args.len()==1 && args[0]=="--case"{return if run_case().await.is_ok(){ExitCode::SUCCESS}else{eprintln!("Rust docs fixture failed");ExitCode::FAILURE}}
 let root=PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");let executable=match std::env::current_exe(){Ok(v)=>v,Err(_)=>return ExitCode::FAILURE};
 let python=std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_|"python3".into());
 let status=Command::new(python).arg(root.join("tests/sdk-conformance/runners/sdk-api-key-docs.py")).args(["--language","rust","--rust-executable"]).arg(executable).args(args).current_dir(root).status();
 if status.is_ok_and(|s|s.success()){ExitCode::SUCCESS}else{eprintln!("Rust docs conformance failed");ExitCode::FAILURE}
}
