//! ADMINISTRATIVE ONE-TIME SETUP ONLY. Normal native CLI login stays browser-pairing-only.
//! Reads one bounded JSON object from a pipe: email, password, current six-digit otp.
//! No credential discovery, environment secrets, legacy-profile import or inference.
#![forbid(unsafe_code)]
use clap::Parser;
use openmates_sdk::{
    Client, ClientIdentity, ClientOptions, crypto, privacy::PrivacyOptions, work::ProjectFilters,
};
use openmates::{
    cli::trusted_account,
    profile::{self, ProfileEnvironment, ProfileOptions},
    runtime_store::RuntimeStore,
    session_runtime,
    storage::StorageMode,
};
use serde_json::Value;
use std::{
    io::{self, IsTerminal, Read},
    path::{Component, Path, PathBuf},
    sync::Arc,
};
use zeroize::{Zeroize, Zeroizing};

const DEV_API: &str = "https://api.dev.openmates.org";
const DEV_APP: &str = "https://app.dev.openmates.org";
const MAX_INPUT: usize = 8192;
type Result<T> = std::result::Result<T, &'static str>;
#[derive(Parser)]
#[command(
    about = "Administrative creation of a new native dev profile; credentials only from bounded JSON stdin."
)]
struct Args {
    #[arg(long)]
    state_dir: PathBuf,
    #[arg(long)]
    api_url: String,
    #[arg(long)]
    expected_account_id: String,
    #[arg(long)]
    expected_email_hash: String,
    #[arg(long)]
    expected_username: String,
    #[arg(long)]
    expected_project_id: String,
    #[arg(long)]
    expected_project_name: String,
}
struct Credentials {
    email: Zeroizing<String>,
    password: Zeroizing<String>,
    otp: Zeroizing<String>,
}
fn read_bounded(mut input: impl Read) -> Result<Zeroizing<Vec<u8>>> {
    let mut bytes = Zeroizing::new(Vec::with_capacity(MAX_INPUT + 1));
    let mut chunk = Zeroizing::new([0u8; 1024]);
    loop {
        let remaining = MAX_INPUT + 1 - bytes.len();
        let n = input
            .read(&mut chunk[..remaining.min(1024)])
            .map_err(|_| "Credential input could not be read.")?;
        if n == 0 {
            return Ok(bytes);
        }
        bytes.extend_from_slice(&chunk[..n]);
        if bytes.len() > MAX_INPUT {
            return Err("Credential JSON exceeds its size limit.");
        }
    }
}
/// A deliberately tiny JSON-string object parser keeps decoded secret buffers
/// zeroizing even on malformed/duplicate input. serde_json scratch buffers are
/// avoided for credentials; all regular SDK protocol JSON remains in the SDK.
struct Input<'a> {
    bytes: &'a [u8],
    at: usize,
}
impl Input<'_> {
    fn whitespace(&mut self) {
        while self
            .bytes
            .get(self.at)
            .is_some_and(|b| matches!(b, b' ' | b'\r' | b'\n' | b'\t'))
        {
            self.at += 1;
        }
    }
    fn byte(&mut self) -> Result<u8> {
        let value = *self
            .bytes
            .get(self.at)
            .ok_or("Malformed credential JSON.")?;
        self.at += 1;
        Ok(value)
    }
    fn expect(&mut self, value: u8) -> Result<()> {
        self.whitespace();
        if self.byte()? != value {
            return Err("Malformed credential JSON.");
        }
        Ok(())
    }
    fn hex(&mut self) -> Result<u16> {
        let mut value = 0u16;
        for _ in 0..4 {
            let byte = self.byte()?;
            let digit = match byte {
                b'0'..=b'9' => byte - b'0',
                b'a'..=b'f' => byte - b'a' + 10,
                b'A'..=b'F' => byte - b'A' + 10,
                _ => return Err("Malformed credential JSON escape."),
            };
            value = (value << 4) | u16::from(digit);
        }
        Ok(value)
    }
    fn string(&mut self) -> Result<Zeroizing<String>> {
        self.expect(b'"')?;
        let mut output = Zeroizing::new(Vec::with_capacity(MAX_INPUT));
        loop {
            match self.byte()? {
                b'"' => break,
                b'\\' => match self.byte()? {
                    b'"' => output.push(b'"'),
                    b'\\' => output.push(b'\\'),
                    b'/' => output.push(b'/'),
                    b'b' => output.push(8),
                    b'f' => output.push(12),
                    b'n' => output.push(b'\n'),
                    b'r' => output.push(b'\r'),
                    b't' => output.push(b'\t'),
                    b'u' => {
                        let first = self.hex()?;
                        let scalar = if (0xD800..=0xDBFF).contains(&first) {
                            if self.byte()? != b'\\' || self.byte()? != b'u' {
                                return Err("Malformed credential JSON surrogate.");
                            }
                            let second = self.hex()?;
                            if !(0xDC00..=0xDFFF).contains(&second) {
                                return Err("Malformed credential JSON surrogate.");
                            }
                            0x10000
                                + ((u32::from(first) - 0xD800) << 10)
                                + (u32::from(second) - 0xDC00)
                        } else {
                            u32::from(first)
                        };
                        let character =
                            char::from_u32(scalar).ok_or("Malformed credential JSON character.")?;
                        let mut encoded = Zeroizing::new([0u8; 4]);
                        output.extend_from_slice(character.encode_utf8(&mut *encoded).as_bytes());
                    }
                    _ => return Err("Malformed credential JSON escape."),
                },
                0..=31 => return Err("Malformed credential JSON string."),
                byte => output.push(byte),
            }
        }
        let value =
            std::str::from_utf8(&output).map_err(|_| "Credential JSON is not valid UTF-8.")?;
        Ok(Zeroizing::new(value.to_owned()))
    }
}
fn parse_credentials(bytes: &[u8]) -> Result<Credentials> {
    if bytes.len() > MAX_INPUT {
        return Err("Credential JSON exceeds its size limit.");
    }
    let mut input = Input { bytes, at: 0 };
    let (mut email, mut password, mut otp) = (None, None, None);
    input.expect(b'{')?;
    loop {
        let name = input.string()?;
        input.expect(b':')?;
        let target = match name.as_str() {
            "email" => &mut email,
            "password" => &mut password,
            "otp" => &mut otp,
            _ => return Err("Credential JSON has an unsupported field."),
        };
        if target.is_some() {
            return Err("Credential JSON has a duplicate field.");
        }
        *target = Some(input.string()?);
        input.whitespace();
        match input.byte()? {
            b'}' => break,
            b',' => {}
            _ => return Err("Malformed credential JSON object."),
        }
    }
    input.whitespace();
    if input.at != bytes.len() {
        return Err("Credential JSON has trailing data.");
    }
    let mut credentials = Credentials {
        email: email.ok_or("Email is required.")?,
        password: password.ok_or("Password is required.")?,
        otp: otp.ok_or("Current OTP is required.")?,
    };
    let email = credentials.email.trim();
    if email.is_empty()
        || email.len() > 320
        || !email.contains('@')
        || email.chars().any(char::is_control)
    {
        return Err("Email is invalid.");
    }
    credentials.email = Zeroizing::new(email.to_lowercase());
    if credentials.password.is_empty() || credentials.password.len() > 4096 {
        return Err("Password length is invalid.");
    }
    if credentials.otp.len() != 6 || !credentials.otp.bytes().all(|b| b.is_ascii_digit()) {
        return Err("A current six-digit OTP is required.");
    }
    Ok(credentials)
}
fn canonical_uuid(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok_and(|id| id.to_string() == value)
}
fn validate_args(args: &Args) -> Result<()> {
    if args.api_url != DEV_API {
        return Err("Administrative setup is pinned to the dev API.");
    }
    if !args.state_dir.is_absolute()
        || args.state_dir.file_name().is_none()
        || args
            .state_dir
            .components()
            .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
    {
        return Err("An explicit normalized absolute state directory is required.");
    }
    if !canonical_uuid(&args.expected_account_id) || !canonical_uuid(&args.expected_project_id) {
        return Err("Expected account and Project IDs must be canonical UUIDs.");
    }
    if crypto::decode_key(&args.expected_email_hash).is_err() {
        return Err("Expected email hash must encode exactly 32 bytes.");
    }
    for value in [&args.expected_username, &args.expected_project_name] {
        if value.trim().is_empty() || value.len() > 512 || value.chars().any(char::is_control) {
            return Err("Expected username and Project name are required.");
        }
    }
    Ok(())
}
fn verify_identity(args: &Args, credentials: &Credentials, client: &Client) -> Result<()> {
    let user = client.user();
    verify_user(args, user)?;
    let session = client
        .session()
        .ok_or("Authenticated session is missing.")?;
    if session.api_url != DEV_API
        || session.active_team_id.is_some()
        || session.hashed_email != args.expected_email_hash
        || session.hashed_email != crypto::hash_email(&credentials.email)
    {
        return Err("Authenticated session does not match the expected Personal dev account.");
    }
    Ok(())
}
fn verify_user(args: &Args, user: &Value) -> Result<()> {
    trusted_account::verify(Some(&args.expected_account_id), user)
        .map_err(|_| "Authenticated account does not match the expected account.")?;
    if user["username"].as_str() != Some(args.expected_username.as_str()) {
        return Err("Authenticated username does not match the expected username.");
    }
    Ok(())
}
fn verify_project(args: &Args, project: &Value) -> Result<()> {
    if project["project_id"].as_str() != Some(args.expected_project_id.as_str())
        || project["name"].as_str() != Some(args.expected_project_name.as_str())
    {
        return Err("Existing Personal Project does not match the expected Project.");
    }
    Ok(())
}
#[cfg(unix)]
mod owned {
    use super::*;
    use fs2::FileExt;
    use rustix::fs::{AtFlags, Mode, OFlags};
    use std::{ffi::OsString, fs::File, os::unix::fs::MetadataExt};
    // MetadataExt::dev widens native dev_t with `as u64`, including signed Darwin IDs.
    #[allow(clippy::unnecessary_cast)]
    pub(super) fn device_matches(expected: u64, native: rustix::fs::Dev) -> bool {
        expected == native as u64
    }
    fn directory(path: &Path) -> Result<File> {
        let mut directory = File::from(
            rustix::fs::open(
                "/",
                OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC,
                Mode::empty(),
            )
            .map_err(|_| "State parent could not be opened.")?,
        );
        for component in path.components() {
            match component {
                Component::RootDir => {}
                Component::Normal(name) => {
                    directory = File::from(
                        rustix::fs::openat(
                            &directory,
                            name,
                            OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                            Mode::empty(),
                        )
                        .map_err(|_| "State parent must already exist without symlinks.")?,
                    )
                }
                _ => return Err("State path must be normalized."),
            }
        }
        Ok(directory)
    }
    fn private(file: &File) -> Result<()> {
        let meta = file
            .metadata()
            .map_err(|_| "State metadata is unavailable.")?;
        if !meta.is_dir()
            || meta.uid() != rustix::process::geteuid().as_raw()
            || meta.mode() & 0o777 != 0o700
        {
            return Err("New state directory must be owner-only mode0700.");
        }
        Ok(())
    }
    pub struct NewProfile {
        parent: File,
        directory: File,
        name: OsString,
        path: PathBuf,
    }
    impl NewProfile {
        pub fn create(path: &Path) -> Result<Self> {
            let parent = directory(path.parent().ok_or("State parent is required.")?)?;
            let meta = parent
                .metadata()
                .map_err(|_| "State parent metadata is unavailable.")?;
            if meta.uid() != rustix::process::geteuid().as_raw() || meta.mode() & 0o022 != 0 {
                return Err("State parent must be owned and not writable by other users.");
            }
            let name = path
                .file_name()
                .ok_or("State profile name is required.")?
                .to_owned();
            rustix::fs::mkdirat(&parent,&name,Mode::RUSR|Mode::WUSR|Mode::XUSR).map_err(|_|"State directory already exists or could not be exclusively created; it was preserved.")?;
            let directory = File::from(
                rustix::fs::openat(
                    &parent,
                    &name,
                    OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .map_err(|_| "New state directory could not be opened.")?,
            );
            private(&directory)?;
            parent
                .sync_all()
                .map_err(|_| "New state directory could not be synchronized.")?;
            Ok(Self {
                parent,
                directory,
                name,
                path: path.to_owned(),
            })
        }
        pub fn verify(&self) -> Result<()> {
            private(&self.directory)?;
            let current = directory(&self.path)?;
            private(&current)?;
            let expected = self
                .directory
                .metadata()
                .map_err(|_| "State identity is unavailable.")?;
            let actual = current
                .metadata()
                .map_err(|_| "State identity is unavailable.")?;
            let leaf = rustix::fs::statat(&self.parent, &self.name, AtFlags::SYMLINK_NOFOLLOW)
                .map_err(|_| "State path identity changed.")?;
            if expected.dev() != actual.dev()
                || expected.ino() != actual.ino()
                || !device_matches(expected.dev(), leaf.st_dev)
                || expected.ino() != leaf.st_ino
            {
                return Err("New state path identity changed.");
            }
            Ok(())
        }
        /// Called only after Store::clear and dropping its lifetime lock. Never
        /// recursively delete: preserve unexpected files or a replaced profile.
        pub fn remove(self) -> Result<()> {
            self.verify()?;
            let flags = OFlags::RDWR | OFlags::NOFOLLOW | OFlags::CLOEXEC;
            let runtime =
                match rustix::fs::openat(&self.directory, "runtime.lock", flags, Mode::empty()) {
                    Ok(fd) => {
                        let file = File::from(fd);
                        file.try_lock_exclusive()
                            .map_err(|_| "New profile is in use; cleanup was refused.")?;
                        Some(file)
                    }
                    Err(rustix::io::Errno::NOENT) => None,
                    Err(_) => return Err("New profile lock could not be checked."),
                };
            let mut names = vec![];
            for entry in rustix::fs::Dir::read_from(&self.directory)
                .map_err(|_| "New profile could not be enumerated.")?
            {
                let entry = entry.map_err(|_| "New profile entry could not be checked.")?;
                let name = entry.file_name();
                if name.to_bytes() == b"." || name.to_bytes() == b".." {
                    continue;
                }
                if !matches!(
                    name.to_bytes(),
                    b"runtime.lock"
                        | b"session.lock"
                        | b"trusted_account.json"
                        | b"revocation.json"
                        | b"revocation.lock"
                ) {
                    return Err("Unexpected new profile files were preserved for inspection.");
                }
                let fd = rustix::fs::openat(
                    &self.directory,
                    name,
                    OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::NONBLOCK | OFlags::CLOEXEC,
                    Mode::empty(),
                )
                .map_err(|_| "Unsafe cleanup entry was preserved.")?;
                let metadata = File::from(fd)
                    .metadata()
                    .map_err(|_| "Cleanup entry metadata is unavailable.")?;
                if !metadata.is_file()
                    || metadata.uid() != rustix::process::geteuid().as_raw()
                    || metadata.mode() & 0o777 != 0o600
                    || metadata.nlink() != 1
                {
                    return Err("Unsafe cleanup entry was preserved.");
                }
                names.push(name.to_owned());
            }
            self.verify()?;
            for name in names {
                rustix::fs::unlinkat(&self.directory, name, AtFlags::empty())
                    .map_err(|_| "New profile file cleanup failed.")?;
            }
            self.directory
                .sync_all()
                .map_err(|_| "New profile cleanup could not be synchronized.")?;
            rustix::fs::unlinkat(&self.parent, &self.name, AtFlags::REMOVEDIR)
                .map_err(|_| "New profile directory cleanup failed.")?;
            self.parent
                .sync_all()
                .map_err(|_| "Profile parent cleanup could not be synchronized.")?;
            drop(runtime);
            Ok(())
        }
    }
}
#[cfg(unix)]
async fn rollback(store: RuntimeStore, owned: owned::NewProfile) -> Result<()> {
    let cleared = store.clear().await;
    drop(store);
    cleared.map_err(
        |_| "Administrative setup failed and credential cleanup failed; inspect the new path.",
    )?;
    owned.remove().map_err(
        |_| "Administrative setup failed and new-directory cleanup failed; inspect the new path.",
    )
}
#[cfg(unix)]
async fn run(args: Args, mut credentials: Credentials) -> Result<StorageMode> {
    validate_args(&args)?;
    let home = directories::BaseDirs::new().ok_or("Home directory is unavailable.")?;
    let resolved = profile::resolve(
        ProfileOptions {
            state_dir: Some(args.state_dir.clone()),
            api_url: Some(DEV_API.into()),
            ..Default::default()
        },
        ProfileEnvironment::default(),
        home.home_dir(),
    )
    .map_err(|_| "Explicit native profile path is invalid.")?;
    let owned = owned::NewProfile::create(&resolved.state_dir)?;
    let store = match RuntimeStore::new(Some(resolved.state_dir.clone()), false).await {
        Ok(store) => store,
        Err(_) => {
            owned.remove().map_err(
                |_| "Store creation failed and new-state cleanup failed; inspect the new path.",
            )?;
            return Err("Native Store could not be opened.");
        }
    };
    let result = async {
        owned.verify()?;
        if store
            .load(None)
            .await
            .map_err(|_| "New profile state could not be checked.")?
            .is_some()
            || trusted_account::load(&resolved.state_dir)
                .map_err(|_| "New profile trust state could not be checked.")?
                .is_some()
        {
            return Err("New profile unexpectedly contains credentials or trust state.");
        }
        let mut client = Client::with_options(
            DEV_API,
            None,
            ClientOptions {
                identity: ClientIdentity::Cli,
                interactive: false,
                app_url: Some(DEV_APP.into()),
                privacy: PrivacyOptions { enhanced: false },
                private_operation_gate: Some(Arc::new(|| Err(openmates_sdk::Error::Forbidden))),
            },
        )
        .map_err(|_| "Pinned administrative client could not be constructed.")?;
        client
            .login_password(
                &credentials.email,
                &credentials.password,
                Some(&credentials.otp),
            )
            .await
            .map_err(|_| "Administrative password/OTP sign-in failed.")?;
        credentials.password.zeroize();
        credentials.otp.zeroize();
        client
            .validate_session()
            .await
            .map_err(|_| "Administrative session verification failed.")?;
        verify_identity(&args, &credentials, &client)?;
        let project = client
            .projects()
            .with_filters(ProjectFilters {
                personal: true,
                ..Default::default()
            })
            .show(&args.expected_project_id)
            .await
            .map_err(|_| "Expected Personal Project could not be read.")?;
        verify_project(&args, &project)?;
        verify_identity(&args, &credentials, &client)?;
        owned.verify()?;
        store
            .begin_session(
                client
                    .clone_session()
                    .ok_or("Verified session is missing.")?,
            )
            .await
            .map_err(
                |_| "Fresh native session admission failed; logout protection was preserved.",
            )?;
        session_runtime::persist(&mut client, &store, None)
            .await
            .map_err(
                |_| "Native credential/cache persistence or revision acknowledgement failed.",
            )?;
        owned.verify()?;
        trusted_account::save(&resolved.state_dir, &args.expected_account_id)
            .map_err(|_| "Native trusted-account marker publication failed.")?;
        owned.verify()?;
        let trust = trusted_account::load(&resolved.state_dir)
            .map_err(|_| "Native trusted-account marker reread failed.")?;
        trusted_account::verify(trust.as_deref(), client.user())
            .map_err(|_| "Native trusted-account marker does not match.")?;
        let saved = store
            .load(None)
            .await
            .map_err(|_| "Durable native session could not be reread.")?
            .ok_or("Durable native session is missing.")?;
        let live = client.session().ok_or("Verified session is missing.")?;
        if saved.api_url != DEV_API
            || saved.hashed_email != args.expected_email_hash
            || saved.master_key.as_ref() != live.master_key.as_ref()
            || saved.cookies != live.cookies
        {
            return Err("Durable credentials differ from the acknowledged session.");
        }
        match store
            .storage_mode()
            .await
            .map_err(|_| "Native credential protection could not be checked.")?
        {
            Some(mode @ (StorageMode::OsKeyring | StorageMode::RestrictedLocalFile)) => Ok(mode),
            _ => Err("Native credential protection differs from the requested default policy."),
        }
    }
    .await;
    match result {
        Ok(mode) => Ok(mode),
        Err(error) => {
            rollback(store, owned).await?;
            Err(error)
        }
    }
}
#[tokio::main]
async fn main() {
    let result=async {
        let args=Args::parse();validate_args(&args)?;
        if io::stdin().is_terminal(){return Err("Provide credential JSON through a bounded pipe and close stdin; interactive input is disabled.");}
        let bytes=read_bounded(io::stdin().lock())?;let credentials=parse_credentials(&bytes)?;drop(bytes);
        #[cfg(unix)] {run(args,credentials).await}
        #[cfg(not(unix))] {let _=(args,credentials);Err("Administrative profile setup requires native Unix ownership checks.")}
    }.await;
    match result {
        Ok(StorageMode::OsKeyring) => {
            println!("Administrative native profile created. Storage: OS keyring.")
        }
        Ok(StorageMode::RestrictedLocalFile) => println!(
            "Administrative native profile created. Storage: owner-only local key file (0600); OS keyring is unavailable."
        ),
        Ok(StorageMode::EncryptedVault) => unreachable!(),
        Err(message) => {
            eprintln!("Administrative setup failed: {message}");
            std::process::exit(1);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    // contract-test-file: tooling
    #[cfg(unix)]
    #[test]
    fn native_device_comparison_matches_standard_metadata_without_rejecting_signed_ids() {
        use std::os::unix::fs::MetadataExt;
        let file = tempfile::tempfile().unwrap();
        let expected = file.metadata().unwrap().dev();
        let native = rustix::fs::fstat(&file).unwrap().st_dev;
        assert!(owned::device_matches(expected, native));
        assert!(!owned::device_matches(expected.wrapping_add(1), native));
        #[cfg(target_os = "macos")]
        {
            assert!(owned::device_matches(u64::MAX, -1));
            assert!(!owned::device_matches(u64::from(u32::MAX), -1));
            assert!(owned::device_matches(i32::MIN as u64, i32::MIN));
        }
    }
    fn args() -> Args {
        Args {
            state_dir: "/private/new-profile".into(),
            api_url: DEV_API.into(),
            expected_account_id: "11111111-1111-4111-8111-111111111111".into(),
            expected_email_hash: crypto::hash_email("person@example.invalid"),
            expected_username: "synthetic-owner".into(),
            expected_project_id: "22222222-2222-4222-8222-222222222222".into(),
            expected_project_name: "Synthetic engineering".into(),
        }
    }
    #[test]
    fn bounded_stdin_stops_at_limit_without_reading_the_rest() {
        let input = vec![b'x'; MAX_INPUT + 1000];
        let mut cursor = io::Cursor::new(input);
        assert!(read_bounded(&mut cursor).is_err());
        assert_eq!(cursor.position(), (MAX_INPUT + 1) as u64);
    }
    #[test]
    fn parses_escaped_unicode_credentials_without_secret_debug() {
        let credentials=parse_credentials(br#" {"email":"  PERSON@Example.invalid  ","password":"quoted\" \\ \uD83D\uDD10","otp":"123456"} "#).unwrap_or_else(|_|panic!("credential parser"));
        assert!(credentials.password.ends_with('🔐'));
        assert_eq!(credentials.otp.as_str(), "123456");
        assert_eq!(
            crypto::hash_email(&credentials.email),
            args().expected_email_hash
        );
    }
    #[test]
    fn rejects_duplicate_unknown_nested_missing_trailing_and_invalid_otp() {
        for raw in [
            r#"{"email":"person@example.invalid","password":"x","otp":"123456","otp":"123456"}"#,
            r#"{"email":"person@example.invalid","password":"x","otp":"123456","secret":"x"}"#,
            r#"{"email":"person@example.invalid","password":{},"otp":"123456"}"#,
            r#"{"email":"person@example.invalid","password":"x"}"#,
            r#"{"email":"person@example.invalid","password":"x","otp":"12x456"}"#,
            r#"{"email":"person@example.invalid","password":"x","otp":"123456"}{}"#,
        ] {
            assert!(parse_credentials(raw.as_bytes()).is_err());
        }
    }
    #[test]
    fn endpoint_identity_and_path_flags_fail_closed() {
        let mut value = args();
        assert!(validate_args(&value).is_ok());
        value.api_url = "https://api.openmates.org".into();
        assert!(validate_args(&value).is_err());
        value = args();
        value.state_dir = "relative".into();
        assert!(validate_args(&value).is_err());
        value = args();
        value.expected_account_id = "not-an-account".into();
        assert!(validate_args(&value).is_err());
        value = args();
        value.expected_email_hash = "invalid".into();
        assert!(validate_args(&value).is_err());
    }
    #[test]
    fn verifies_exact_existing_project() {
        let value = args();
        assert!(verify_project(&value,&serde_json::json!({"project_id":value.expected_project_id,"name":value.expected_project_name})).is_ok());
        assert!(
            verify_project(
                &value,
                &serde_json::json!({"project_id":value.expected_project_id,"name":"other"})
            )
            .is_err()
        );
    }
    #[cfg(unix)]
    #[test]
    fn new_profile_reservation_never_overwrites_and_only_removes_owned_empty_state() {
        use std::os::unix::fs::PermissionsExt;
        let parent = tempfile::tempdir().unwrap();
        std::fs::set_permissions(parent.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let target = parent.path().join("new-profile");
        let owned = owned::NewProfile::create(&target).unwrap_or_else(|_| panic!("new profile"));
        assert!(owned::NewProfile::create(&target).is_err());
        owned
            .remove()
            .unwrap_or_else(|_| panic!("remove new profile"));
        assert!(!target.exists());
    }
    #[test]
    fn verifies_both_expected_account_and_exact_username() {
        let value = args();
        let user =
            serde_json::json!({"id":value.expected_account_id,"username":value.expected_username});
        assert!(verify_user(&value, &user).is_ok());
        for mismatch in [
            serde_json::json!({"id":"33333333-3333-4333-8333-333333333333","username":value.expected_username}),
            serde_json::json!({"id":value.expected_account_id,"username":"other"}),
        ] {
            assert!(verify_user(&value, &mismatch).is_err());
        }
    }
    #[cfg(unix)]
    #[test]
    fn rollback_preserves_unexpected_files_and_replaced_paths() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let parent = tempfile::tempdir().unwrap();
        std::fs::set_permissions(parent.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let target = parent.path().join("new-profile");
        let owned = owned::NewProfile::create(&target).unwrap_or_else(|_| panic!("new profile"));
        std::fs::write(target.join("unexpected"), b"preserve").unwrap();
        assert!(owned.remove().is_err());
        assert!(target.join("unexpected").exists());
        let second = parent.path().join("second-profile");
        let owned = owned::NewProfile::create(&second).unwrap_or_else(|_| panic!("new profile"));
        let original = parent.path().join("moved-profile");
        std::fs::rename(&second, &original).unwrap();
        symlink(&original, &second).unwrap();
        assert!(owned.remove().is_err());
        assert!(original.exists());
        assert!(
            std::fs::symlink_metadata(&second)
                .unwrap()
                .file_type()
                .is_symlink()
        );
    }
    #[cfg(unix)]
    #[test]
    fn rollback_preserves_unsafe_revocation_entries() {
        use std::os::unix::fs::{PermissionsExt, symlink};
        let parent = tempfile::tempdir().unwrap();
        std::fs::set_permissions(parent.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let outside = parent.path().join("preserve");
        std::fs::write(&outside, b"preserve").unwrap();
        std::fs::set_permissions(&outside, std::fs::Permissions::from_mode(0o600)).unwrap();
        for (index, name) in ["revocation.json", "revocation.lock"]
            .into_iter()
            .enumerate()
        {
            let target = parent.path().join(format!("new-{index}"));
            let owned =
                owned::NewProfile::create(&target).unwrap_or_else(|_| panic!("new profile"));
            if index == 0 {
                symlink(&outside, target.join(name)).unwrap();
            } else {
                std::fs::hard_link(&outside, target.join(name)).unwrap();
            }
            assert!(owned.remove().is_err());
            assert_eq!(std::fs::read(&outside).unwrap(), b"preserve");
            assert!(std::fs::symlink_metadata(target.join(name)).is_ok());
        }
    }
    #[cfg(unix)]
    #[tokio::test]
    async fn marker_or_save_failure_clears_new_durable_credentials_and_directory() {
        use std::os::unix::fs::PermissionsExt;
        let parent = tempfile::tempdir().unwrap();
        std::fs::set_permissions(parent.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        for marker_failure in [true, false] {
            let target = parent.path().join(if marker_failure {
                "marker-failure"
            } else {
                "save-failure"
            });
            let owned =
                owned::NewProfile::create(&target).unwrap_or_else(|_| panic!("new profile"));
            // Unit tests use an explicit vault so they never access an OS keyring.
            let store = RuntimeStore::new(Some(target.clone()), true).await.unwrap();
            let session = openmates_sdk::Session {
                api_url: DEV_API.into(),
                session_id: "synthetic-session".into(),
                cookies: std::collections::BTreeMap::new(),
                ws_token: None,
                master_key: Zeroizing::new([7; 32]),
                hashed_email: args().expected_email_hash,
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            };
            let mut client = Client::new(DEV_API, Some(session)).unwrap();
            session_runtime::persist(
                &mut client,
                &store,
                Some(Zeroizing::new("synthetic local vault password".into())),
            )
            .await
            .unwrap();
            assert!(target.join("session.json").exists());
            if marker_failure {
                assert!(trusted_account::save(&target, "").is_err());
            } else {
                assert!(
                    store
                        .save(
                            client.clone_session().unwrap(),
                            Some(Zeroizing::new("wrong synthetic vault password".into()))
                        )
                        .await
                        .is_err()
                );
            }
            rollback(store, owned)
                .await
                .unwrap_or_else(|_| panic!("rollback"));
            assert!(!target.exists());
        }
    }
}
