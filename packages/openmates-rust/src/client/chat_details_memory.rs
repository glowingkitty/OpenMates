//! Maintained memory-request display coalescing, shared headless projection only.
//! Ordered JSON preserves the content string's property order through JSON.stringify
//! semantics. Source data never becomes consent, disclosure or execution authority.
use super::*;
use serde::{
    de::{self, MapAccess, SeqAccess, Visitor},
    ser::{SerializeMap, SerializeSeq},
};
#[derive(Default)]
enum Ordered {
    #[default]
    Null,
    Bool(bool),
    Number(serde_json::Number),
    String(String),
    Array(Vec<Ordered>),
    Object(Vec<(String, Ordered)>),
}
impl Wipe for Ordered {
    fn wipe(&mut self) {
        match self {
            Self::String(v) => v.wipe(),
            Self::Array(v) => v.wipe(),
            Self::Object(values) => {
                for (k, v) in values {
                    k.wipe();
                    v.wipe();
                }
            }
            _ => {}
        }
    }
}
impl Ordered {
    fn field(&self, name: &str) -> Option<&Self> {
        if let Self::Object(values) = self {
            values.iter().find(|(key, _)| key == name).map(|(_, v)| v)
        } else {
            None
        }
    }
    fn text(&self) -> Option<&str> {
        if let Self::String(v) = self {
            Some(v)
        } else {
            None
        }
    }
    fn take(&mut self, name: &str) -> Self {
        if let Self::Object(values) = self {
            if let Some((_, v)) = values.iter_mut().find(|(key, _)| key == name) {
                return std::mem::take(v);
            }
        }
        Self::Null
    }
    fn set(&mut self, name: &str, value: Self) {
        if let Self::Object(values) = self {
            if let Some((_, v)) = values.iter_mut().find(|(key, _)| key == name) {
                v.wipe();
                *v = value;
            } else {
                values.push((name.into(), value));
            }
        }
    }
    fn count(&self) -> Option<u64> {
        if let Self::Number(v) = self {
            v.as_f64()
                .filter(|n| {
                    n.is_finite() && n.fract() == 0.0 && *n >= 0.0 && *n <= 9_007_199_254_740_991.0
                })
                .map(|n| n as u64)
        } else {
            None
        }
    }
}
impl Serialize for Ordered {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        match self {
            Self::Null => s.serialize_unit(),
            Self::Bool(v) => s.serialize_bool(*v),
            Self::Number(v) => v.serialize(s),
            Self::String(v) => s.serialize_str(v),
            Self::Array(values) => {
                let mut out = s.serialize_seq(Some(values.len()))?;
                for v in values {
                    out.serialize_element(v)?;
                }
                out.end()
            }
            Self::Object(values) => {
                let mut out = s.serialize_map(Some(values.len()))?;
                for (k, v) in values {
                    out.serialize_entry(k, v)?;
                }
                out.end()
            }
        }
    }
}
struct OrderedVisitor;
impl<'de> Visitor<'de> for OrderedVisitor {
    type Value = Ordered;
    fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        f.write_str("bounded JSON data")
    }
    fn visit_unit<E: de::Error>(self) -> std::result::Result<Ordered, E> {
        Ok(Ordered::Null)
    }
    fn visit_none<E: de::Error>(self) -> std::result::Result<Ordered, E> {
        Ok(Ordered::Null)
    }
    fn visit_bool<E: de::Error>(self, v: bool) -> std::result::Result<Ordered, E> {
        Ok(Ordered::Bool(v))
    }
    fn visit_i64<E: de::Error>(self, v: i64) -> std::result::Result<Ordered, E> {
        Ok(Ordered::Number(v.into()))
    }
    fn visit_u64<E: de::Error>(self, v: u64) -> std::result::Result<Ordered, E> {
        Ok(Ordered::Number(v.into()))
    }
    fn visit_f64<E: de::Error>(self, v: f64) -> std::result::Result<Ordered, E> {
        if v.is_finite() && v.fract() == 0.0 && v.abs() <= 9_007_199_254_740_991.0 {
            Ok(Ordered::Number((v as i64).into()))
        } else {
            serde_json::Number::from_f64(v)
                .map(Ordered::Number)
                .ok_or_else(|| E::custom("finite JSON number required"))
        }
    }
    fn visit_str<E: de::Error>(self, v: &str) -> std::result::Result<Ordered, E> {
        Ok(Ordered::String(v.into()))
    }
    fn visit_string<E: de::Error>(self, v: String) -> std::result::Result<Ordered, E> {
        Ok(Ordered::String(v))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> std::result::Result<Ordered, A::Error> {
        let mut out = Plain::new(Vec::new());
        while let Some(v) = seq.next_element()? {
            out.push(v);
        }
        Ok(Ordered::Array(out.into_inner()))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Ordered, A::Error> {
        let mut out = Plain::new(Ordered::Object(vec![]));
        while let Some((key, value)) = map.next_entry::<String, Ordered>()? {
            out.set(&key, value);
        }
        Ok(out.into_inner())
    }
}
impl<'de> Deserialize<'de> for Ordered {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        d.deserialize_any(OrderedVisitor)
    }
}
fn request(content: &str, client_id: &str) -> Option<Plain<Ordered>> {
    let mut value = Plain::new(serde_json::from_str::<Ordered>(content).ok()?);
    if value.field("type").and_then(Ordered::text) != Some("app_settings_memories_request")
        || value.field("request_id").and_then(Ordered::text).is_none()
        || value
            .field("user_message_id")
            .and_then(Ordered::text)
            .is_none()
    {
        return None;
    }
    let Some(Ordered::Array(keys)) = value.field("requested_keys") else {
        return None;
    };
    if keys.iter().any(|v| v.text().is_none()) {
        return None;
    }
    let Some(Ordered::Array(categories)) = value.field("categories") else {
        return None;
    };
    if categories.iter().any(|v| {
        v.field("appId").and_then(Ordered::text).is_none()
            || v.field("itemType").and_then(Ordered::text).is_none()
    }) {
        return None;
    }
    let legacy = value.field("count_semantics_version").is_none()
        && value.field("request_id").and_then(Ordered::text) == Some(client_id);
    let Ordered::Array(mut categories) = value.take("categories") else {
        return None;
    };
    for category in &mut categories {
        if legacy
            || category
                .field("entryCount")
                .and_then(Ordered::count)
                .is_none()
        {
            category.set("entryCount", Ordered::Null);
        }
    }
    value.set("categories", Ordered::Array(categories));
    Some(value)
}
fn merge(first: &mut Ordered, second: &mut Ordered) -> Result<()> {
    let (Ordered::Array(a), Ordered::Array(b)) =
        (first.take("requested_keys"), second.take("requested_keys"))
    else {
        return Err(Error::Protocol);
    };
    let mut keys = a;
    keys.extend(b);
    keys.sort_by(|a, b| {
        a.text()
            .unwrap_or("")
            .encode_utf16()
            .cmp(b.text().unwrap_or("").encode_utf16())
    });
    keys.dedup_by(|a, b| a.text() == b.text());
    let (Ordered::Array(a), Ordered::Array(b)) =
        (first.take("categories"), second.take("categories"))
    else {
        return Err(Error::Protocol);
    };
    let mut categories = BTreeMap::<String, Ordered>::new();
    for category in a.into_iter().chain(b) {
        let key = format!(
            "{}-{}",
            category
                .field("appId")
                .and_then(Ordered::text)
                .ok_or(Error::Protocol)?,
            category
                .field("itemType")
                .and_then(Ordered::text)
                .ok_or(Error::Protocol)?
        );
        let replace = categories.get(&key).is_none_or(|old| {
            category
                .field("entryCount")
                .and_then(Ordered::count)
                .is_some_and(|count| {
                    old.field("entryCount")
                        .and_then(Ordered::count)
                        .is_none_or(|old| count > old)
                })
        });
        if replace {
            if let Some(mut old) = categories.insert(key, category) {
                old.wipe();
            }
        } else {
            let mut ignored = category;
            ignored.wipe();
        }
    }
    // Existing pinned ICU/locale dependency, never ambient host settings. The
    // maintained categories are canonical app/item keys; no new locale API.
    let locale: icu_locale_core::Locale = "en-US".parse().map_err(|_| Error::Protocol)?;
    let collator = icu_collator::Collator::try_new(
        locale.into(),
        icu_collator::options::CollatorOptions::default(),
    )
    .map_err(|_| Error::Protocol)?;
    let mut categories = categories.into_iter().collect::<Vec<_>>();
    categories.sort_by(|(a, _), (b, _)| collator.compare(a, b));
    first.set("count_semantics_version", Ordered::Number(1.into()));
    first.set("requested_keys", Ordered::Array(keys));
    first.set(
        "categories",
        Ordered::Array(categories.into_iter().map(|(_, v)| v).collect()),
    );
    Ok(())
}
pub(super) fn coalesce(messages: &mut Vec<ChatDetailsMessage>) -> Result<()> {
    let mut result = Plain::new(Vec::<ChatDetailsMessage>::new());
    let mut requests = BTreeMap::<(String, String), usize>::new();
    for mut message in std::mem::take(messages) {
        let candidate = if message.role == "system" {
            request(&message.content, &message.client_message_id)
        } else {
            None
        };
        let Some(mut current) = candidate else {
            result.push(message);
            continue;
        };
        let key = (
            current
                .field("user_message_id")
                .and_then(Ordered::text)
                .ok_or(Error::Protocol)?
                .to_owned(),
            current
                .field("request_id")
                .and_then(Ordered::text)
                .ok_or(Error::Protocol)?
                .to_owned(),
        );
        if let Some(&index) = requests.get(&key) {
            let mut previous = request(&result[index].content, &result[index].client_message_id)
                .ok_or(Error::Protocol)?;
            merge(&mut previous, &mut current)?;
            let content = serde_json::to_string(&*previous)?;
            result[index].content.zeroize();
            result[index].content = content;
            message.wipe();
        } else {
            let content = serde_json::to_string(&*current)?;
            message.content.zeroize();
            message.content = content;
            requests.insert(key, result.len());
            result.push(message);
        }
    }
    *messages = result.into_inner();
    Ok(())
}
