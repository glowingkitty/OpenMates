//! Edit-with-options refusals: new-chat-only options, a bad Project id and
//! empty edits are refused before the message is touched.
use super::edit_request::check_edit;
use super::{SendTurnOptions, actor_tests::CHAT};
use crate::{client::ReservedTurnIds, error::Error};

#[test]
fn edit_refuses_new_chat_options_and_bad_input() {
    let refused = [
        SendTurnOptions {
            incognito: true,
            ..SendTurnOptions::default()
        },
        SendTurnOptions {
            slug: Some("kitchen-renovation".into()),
            ..SendTurnOptions::default()
        },
        SendTurnOptions {
            reserved: ReservedTurnIds {
                chat_id: Some("66666666-6666-4666-8666-666666666666".into()),
                message_id: None,
            },
            ..SendTurnOptions::default()
        },
        SendTurnOptions {
            project_id: Some("not-a-uuid".into()),
            ..SendTurnOptions::default()
        },
    ];
    for options in refused {
        assert!(matches!(
            check_edit(CHAT, "synthetic edit", &options),
            Err(Error::Invalid(_))
        ));
    }
    assert!(matches!(
        check_edit(CHAT, "  ", &SendTurnOptions::default()),
        Err(Error::Invalid(_))
    ));
}

#[test]
fn edit_accepts_project_and_reserved_message_id() {
    let options = SendTurnOptions {
        project_id: Some("77777777-7777-4777-8777-777777777777".into()),
        reserved: ReservedTurnIds {
            chat_id: None,
            message_id: Some("66666666-6666-4666-8666-666666666666".into()),
        },
        ..SendTurnOptions::default()
    };
    check_edit(CHAT, "synthetic edit", &options).unwrap();
}
