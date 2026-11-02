//! Direct PyO3 byte/public-wire adapters; no CLI/profile or Python crypto logic.
use crate::{BindingError,remote_crypto::{RemoteHandshakeHandle,RemoteSessionHandle}};
use pyo3::{prelude::*,types::PyBytes,exceptions::PyRuntimeError};
fn error(value:BindingError)->PyErr { PyRuntimeError::new_err(value.json()) }
#[pyclass(name="NativeRemoteHandshake",module="openmates._native")]
struct PythonRemoteHandshake { handle:RemoteHandshakeHandle }
#[pymethods]
impl PythonRemoteHandshake {
    #[new]
    fn new(key:&Bound<'_,PyBytes>,identity_json:String,role:String)->PyResult<Self> {
        RemoteHandshakeHandle::new(key.as_bytes(),identity_json.as_bytes(),&role).map(|handle|Self{handle}).map_err(error)
    }
    fn handshake_json(&self)->PyResult<String> {self.handle.handshake_json().map_err(error)}
    fn finish(&self,remote_json:String)->PyResult<PythonRemoteSession> {self.handle.finish(remote_json.as_bytes()).map(|handle|PythonRemoteSession{handle}).map_err(error)}
    fn close(&self)->PyResult<()> {self.handle.close().map_err(error)}
}
#[pyclass(name="NativeRemoteSession",module="openmates._native")]
struct PythonRemoteSession { handle:RemoteSessionHandle }
#[pymethods]
impl PythonRemoteSession {
    fn seal(&self,request_id:String,plaintext:&Bound<'_,PyBytes>)->PyResult<String> {self.handle.seal(&request_id,plaintext.as_bytes()).map_err(error)}
    fn open<'py>(&self,py:Python<'py>,request_id:String,envelope_json:String)->PyResult<Bound<'py,PyBytes>> {
        let plaintext=self.handle.open(&request_id,envelope_json.as_bytes()).map_err(error)?;
        Ok(PyBytes::new(py,&plaintext))
    }
    fn open_json_text(&self,request_id:String,envelope_json:String)->PyResult<String> {self.handle.open_json_text(&request_id,envelope_json.as_bytes()).map_err(error)}
    fn close(&self)->PyResult<()> {self.handle.close().map_err(error)}
}
pub(crate) fn register(module:&Bound<'_,PyModule>)->PyResult<()> {
    module.add_class::<PythonRemoteHandshake>()?;
    module.add_class::<PythonRemoteSession>()?;
    Ok(())
}
