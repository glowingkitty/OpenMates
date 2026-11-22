//! Error mapping of the sandbox change preview.
use super::sandbox_change::core_error;
use super::*;

#[test]
fn refusals_keep_their_code_and_rejections_are_protocol_errors() {
    assert!(matches!(
        core_error(HostedFileError::Refused("file_key_unavailable")),
        Error::Invalid("file_key_unavailable")
    ));
    assert!(matches!(
        core_error(HostedFileError::Rejected("stale_base".into())),
        Error::Protocol
    ));
    assert!(matches!(
        core_error(HostedFileError::Core(Error::Forbidden)),
        Error::Forbidden
    ));
}
