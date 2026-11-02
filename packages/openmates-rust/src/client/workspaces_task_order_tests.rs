// contract-test: supporting surface=cli assertions=tasks.surface.semantic-parity
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const TEAM: &str = "22222222-2222-4222-8222-222222222222";
fn row(i: usize, team: bool) -> Value {
    let wrapped = crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap();
    let mut value = json!({"task_id":format!("{i:08x}-1111-4111-8111-111111111111"),"encrypted_task_key":wrapped,"encrypted_title":crypto::encrypt_combined("Private Task",&[8;32]).unwrap(),"status":"todo","position":200-i});
    if team {
        value["hashed_team_id"] = json!(sha256(TEAM));
        value["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":sha256(TEAM),"team_key_epoch":1,"encrypted_task_key":wrapped}]);
    }
    value
}
#[test]
fn adapter_preserves_numeric_positions_title_fallbacks_and_scope_key_fences() {
    for team in [false, true] {
        let c = super::delete_tests::client("http://127.0.0.1:1", team, false);
        let mut value = row(0, team);
        for position in [
            Value::Null,
            json!(-1.25),
            json!(-0.0),
            json!(9007199254740993u64),
            json!(1e308),
        ] {
            value["position"] = position.clone();
            value["encrypted_title"] = Value::Null;
            let item = c.object_item(Workspace::Tasks, &value, &[7; 32]).unwrap();
            assert_eq!(item.fields["position"], position);
            assert_eq!(item.title, "(untitled task)");
        }
        value.as_object_mut().unwrap().remove("position");
        assert!(
            c.object_item(Workspace::Tasks, &value, &[7; 32])
                .unwrap()
                .fields["position"]
                .is_null()
        );
        assert!(c.object_item(Workspace::Tasks, &value, &[9; 32]).is_err());
        if team {
            value["hashed_team_id"] = json!("wrong-team");
            assert!(matches!(
                c.object_item(Workspace::Tasks, &value, &[7; 32]),
                Err(Error::Forbidden)
            ));
        }
    }
    let c = super::delete_tests::client("http://127.0.0.1:1", false, false);
    let projected = c
        .object_item(
            Workspace::Tasks,
            &json!({"task_id":"projection","source":"workflow_run","position":-0.5}),
            &[7; 32],
        )
        .unwrap();
    assert_eq!(projected.title, "Workflow run");
    assert_eq!(projected.fields["position"], -0.5);
    assert_eq!(projected.fields["source"], "workflow_run");
    assert_eq!(projected.fields["read_only"], true);
}
#[tokio::test]
async fn complete_pagination_keeps_wire_order_and_position_metadata_for_personal_and_team() {
    for team in [false, true] {
        let rows = (0..101).map(|i| row(i, team)).collect::<Vec<_>>();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move {
            let mut paths = vec![];
            for page in 0..2 {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut bytes = vec![];
                loop {
                    let mut chunk = [0; 4096];
                    let n = stream.read(&mut chunk).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&chunk[..n]);
                    if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                        break;
                    }
                }
                paths.push(String::from_utf8(bytes).unwrap());
                let body = if page == 0 {
                    json!({"tasks":rows[..100],"complete":false,"next_cursor":rows[99]["task_id"]})
                } else {
                    json!({"tasks":rows[100..],"complete":true,"next_cursor":null})
                }
                .to_string();
                stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
            }
            paths
        });
        let mut c = super::delete_tests::client(&api, team, false);
        if team {
            c.team_key = Some((TEAM.into(), zeroize::Zeroizing::new([7; 32])));
        }
        let items = c.list(Workspace::Tasks).await.unwrap();
        assert_eq!(items.len(), 101);
        assert_eq!(items[0].fields["position"], 200);
        assert_eq!(items[100].fields["position"], 100);
        assert!(items[0].id < items[100].id);
        let requests = server.await.unwrap();
        assert_eq!(requests.len(), 2);
        for request in requests {
            assert!(request.contains("paginate=true"));
            assert_eq!(request.contains(&format!("team_id={TEAM}")), team);
        }
    }
}
