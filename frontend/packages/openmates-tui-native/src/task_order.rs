//! Application-only locale selection. The headless SDK always takes a locale.
use crate::error::{Error, Result};
use openmates_sdk::task_order::TaskOrder;

pub(crate) fn for_host() -> Result<TaskOrder> {
    let values = ["LC_ALL", "LC_MESSAGES", "LANG"].map(|name| std::env::var(name).ok());
    TaskOrder::try_new(&locale(values.iter().map(Option::as_deref))?)
}

fn locale<'a>(values: impl IntoIterator<Item = Option<&'a str>>) -> Result<String> {
    let value = values
        .into_iter()
        .flatten()
        .find(|value| !value.is_empty())
        .unwrap_or("en-US");
    // V8/ICU's C/POSIX fallback is en-US in the qualified Node 24 Linux oracle.
    // No account language or CLI profile is read here. macOS without an explicit
    // locale environment remains a qualified fallback, not an OS preference claim.
    let (base, modifier) = value
        .split_once('@')
        .map_or((value, None), |(base, modifier)| (base, Some(modifier)));
    if modifier.is_some() {
        return Err(Error::Invalid(
            "Task ordering requires a BCP47 locale without a POSIX modifier.",
        ));
    }
    let base = base.split('.').next().unwrap_or(base);
    if matches!(base, "C" | "POSIX") {
        return Ok("en-US".into());
    }
    Ok(base.replace('_', "-"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_host_locale_precedence_and_codesets_do_not_force_english() {
        assert_eq!(
            locale([
                Some("sv_SE.UTF-8"),
                Some("de_DE.UTF-8"),
                Some("en_US.UTF-8")
            ])
            .unwrap(),
            "sv-SE"
        );
        assert_eq!(
            locale([Some(""), Some("tr_TR.UTF-8"), Some("en_US.UTF-8")]).unwrap(),
            "tr-TR"
        );
        assert_eq!(
            locale([None, None, Some("de-DE-u-co-phonebk")]).unwrap(),
            "de-DE-u-co-phonebk"
        );
        for value in ["C", "C.UTF-8", "POSIX"] {
            assert_eq!(locale([Some(value)]).unwrap(), "en-US");
        }
        assert_eq!(locale([None]).unwrap(), "en-US");
        assert!(locale([Some("de_DE@unknown")]).is_err());
        assert!(TaskOrder::try_new(&locale([Some("not a locale")]).unwrap()).is_err());
    }
}
