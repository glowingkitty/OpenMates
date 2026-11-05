//! Maintained response-cookie DATA parsing, shared by ordinary atomic Client
//! merging and the independent metadata credential holder. No auth/IO receipt.
use super::*;
pub(in crate::client) struct ObservedCookie<'a>{pub raw:&'a str,pub name:&'a str,pub value:&'a str}
/// Exact former owned_read pair parsing/application. Validation and original
/// holder publication stay with each owning operation, not this pure helper.
pub(in crate::client) fn apply<'a>(next:&mut BTreeMap<String,String>,header:&'a reqwest::header::HeaderValue)->Result<Option<ObservedCookie<'a>>>{
    let raw=header.to_str().map_err(|_|Error::Protocol)?;
    let pair=raw.split(';').next().unwrap_or("");
    let Some((name,value))=pair.split_once('=')else{return Ok(None)};
    if value.is_empty(){next.remove(name.trim());}else{next.insert(name.trim().to_owned(),value.trim().to_owned());}
    Ok(Some(ObservedCookie{raw,name:name.trim(),value}))
}
