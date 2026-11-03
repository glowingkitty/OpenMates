use super::*;

fn index() -> Vec<SidebarProject> {
    serde_json::from_str(
        r#"[
        {"id":"p1","name":"ignored","folders":[
            {"id":"f1","hash":"h1","parentHash":null,"name":"A"},
            {"id":"f2","hash":"h2","parentHash":"h1","name":"B"},
            {"id":"loop1","hash":"l1","parentHash":"l2","name":"C"},
            {"id":"loop2","hash":"l2","parentHash":"l1","name":"D"}],
         "chats":[
            {"id":"i-root","chatId":"root","folderHash":null},
            {"id":"i-a","chatId":"in-a","folderHash":"h1"},
            {"id":"i-b","chatId":"in-b","folderHash":"h2"}]},
        {"id":"p2","folders":[],"chats":[{"id":"j","chatId":"in-a","folderHash":null},{"id":"k","chatId":"new","folderHash":null}]}
    ]"#,
    )
    .unwrap()
}

fn set(ids: &[&str]) -> HashSet<String> {
    ids.iter().map(|id| (*id).to_owned()).collect()
}

#[test]
fn folder_membership_matches_project_navigation() {
    let p = &index()[0];
    assert_eq!(folder_chat_ids(p, None, false), set(&["root"]));
    assert_eq!(folder_chat_ids(p, Some("f1"), false), set(&["in-a"]));
    assert_eq!(folder_chat_ids(p, Some("f1"), true), set(&["in-a", "in-b"]));
    assert_eq!(
        folder_chat_ids(p, None, true),
        set(&["root", "in-a", "in-b"])
    );
    assert_eq!(
        folder_chat_ids(p, Some("loop1"), true),
        set(&[]),
        "cycles terminate and never expand to root"
    );
    assert!(folder_chat_ids(p, Some("missing"), true).is_empty());
}

#[test]
fn move_persists_destination_links_before_removing_sources() {
    let ids: Vec<String> = ["root", "in-a", "new"]
        .iter()
        .map(|s| (*s).to_owned())
        .collect();
    let ops = plan_placement(&index(), "p1", Some("f2"), &ids, PlacementMode::Move).unwrap();
    assert_eq!(
        ops,
        vec![
            PlacementOp::MoveItem {
                item_id: "i-root".into(),
                chat_id: "root".into()
            },
            PlacementOp::MoveItem {
                item_id: "i-a".into(),
                chat_id: "in-a".into()
            },
            PlacementOp::AddChat {
                chat_id: "new".into()
            },
            PlacementOp::RemoveFromProject {
                project_id: "p2".into(),
                chat_id: "in-a".into()
            },
            PlacementOp::RemoveFromProject {
                project_id: "p2".into(),
                chat_id: "new".into()
            },
        ]
    );
    let add = plan_placement(&index(), "p1", Some("f1"), &ids, PlacementMode::Add).unwrap();
    assert!(
        !add.contains(&PlacementOp::MoveItem {
            item_id: "i-a".into(),
            chat_id: "in-a".into()
        }),
        "already in the folder"
    );
    assert!(
        add.iter()
            .all(|op| !matches!(op, PlacementOp::RemoveFromProject { .. }))
    );
    assert_eq!(
        plan_placement(&index(), "nope", None, &ids, PlacementMode::Add).unwrap_err(),
        Error::Invalid("Project is unavailable")
    );
    assert_eq!(
        plan_placement(&index(), "p1", Some("x"), &ids, PlacementMode::Add).unwrap_err(),
        Error::Invalid("Folder is unavailable")
    );
}

#[test]
fn organizable_and_naming_rules_match_the_web_service() {
    let chat = |id: &str| OrganizableChat {
        chat_id: id.into(),
        team_id: Some("t".into()),
        ..Default::default()
    };
    assert!(assert_organizable(&[chat("a")], Some("t")).is_ok());
    assert_eq!(
        assert_organizable(&[], Some("t")).unwrap_err(),
        NOT_ORGANIZABLE
    );
    assert!(
        assert_organizable(&[chat("a")], None).is_err(),
        "team mismatch"
    );
    for flag in 0..3 {
        let mut c = chat("a");
        match flag {
            0 => c.is_incognito = true,
            1 => c.is_shared_by_others = true,
            _ => c.is_static = true,
        }
        assert!(assert_organizable(&[chat("ok"), c], Some("t")).is_err());
    }
    let personal = OrganizableChat {
        chat_id: "p".into(),
        ..Default::default()
    };
    assert!(assert_organizable(&[personal], None).is_ok());

    let titles: Vec<String> = (0..10).map(|i| format!("{i}{}", "x".repeat(300))).collect();
    let bounded = naming_titles(&titles);
    assert_eq!(bounded.len(), 8);
    assert!(bounded.iter().all(|t| utf16_len(t) == 200));
    assert_eq!(
        validate_project_name(Some("  Trip planning \u{FEFF}")).unwrap(),
        "Trip planning"
    );
    for bad in [None, Some(""), Some(" \n "), Some(&*"y".repeat(201))] {
        assert!(validate_project_name(bad).is_err());
    }
    assert!(validate_project_name(Some(&"🔒".repeat(100))).is_ok());
}
