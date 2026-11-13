//! Safe direct API-key Python ABI; allocation remains inside original guard.
use crate::{ApiKeyBridge,ApiKeyRequest,ApiKeyOutput,BindingError};
use pyo3::{prelude::*,exceptions::PyRuntimeError};
use std::sync::{Arc,Mutex};
use zeroize::Zeroizing;
fn error(e:BindingError)->PyErr{PyRuntimeError::new_err(e.json())}
#[pyclass(name="NativeApiKeyClient",module="openmates._native")]
struct PythonApiKeyClient{bridge:ApiKeyBridge}
#[pymethods]
impl PythonApiKeyClient {
    #[new]
    fn new(options_json:String)->PyResult<Self>{let encoded=Zeroizing::new(options_json);Ok(Self{bridge:ApiKeyBridge::with_identity(&encoded,openmates_sdk::ClientIdentity::Pip).map_err(error)?})}
    fn request(&self)->PyResult<PythonApiKeyRequest>{Ok(PythonApiKeyRequest{request:Arc::new(self.bridge.request().map_err(error)?)})}
    fn cancel(&self)->PyResult<()>{self.bridge.cancel().map_err(error)}
    fn close(&self)->PyResult<()>{self.bridge.close().map_err(error)}
}
#[pyclass(name="NativeApiKeyRequest",module="openmates._native")]
struct PythonApiKeyRequest{request:Arc<ApiKeyRequest>}
#[pymethods]
impl PythonApiKeyRequest {
    fn account_info_prepare<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{
        let request=self.request.clone();
        crate::python_future::future_into_py(py,async move{Ok(PythonApiKeyOutput{output:Mutex::new(Some(request.account_info_prepare().await.map_err(error)?))})})
    }
    fn run_skill_prepare<'py>(&self,py:Python<'py>,app:String,skill:String,input_json:String)->PyResult<Bound<'py,PyAny>>{
        let encoded=Zeroizing::new(input_json);
        let request=self.request.clone();
        crate::python_future::future_into_py(py,async move{Ok(PythonApiKeyOutput{output:Mutex::new(Some(request.run_skill_prepare_guarded(app,skill,encoded).await.map_err(error)?))})})
    }
    fn list_project_sources_raw_prepare<'py>(&self, py: Python<'py>, project: String, filters_json: String) -> PyResult<Bound<'py, PyAny>> {
        let encoded = Zeroizing::new(filters_json);
        let request = self.request.clone();
        crate::python_future::future_into_py(py, async move {
            Ok(PythonApiKeyOutput { output: Mutex::new(Some(request.list_project_sources_raw_prepare_guarded(project, encoded).await.map_err(error)?)) })
        })
    }
    fn cancel(&self){self.request.cancel();}
}
impl Drop for PythonApiKeyRequest{fn drop(&mut self){self.request.cancel();}}
#[pyclass(name="NativeApiKeyOutput",module="openmates._native")]
struct PythonApiKeyOutput{output:Mutex<Option<ApiKeyOutput>>}
#[pymethods]
impl PythonApiKeyOutput {
    fn release_json<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,pyo3::types::PyString>>{
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|Ok(pyo3::types::PyString::new(py,text))).map_err(error)
    }
    fn discard(&self)->PyResult<()>{self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())}
}
pub(crate) fn register(module:&Bound<'_,PyModule>)->PyResult<()>{
    module.add_class::<PythonApiKeyClient>()?;module.add_class::<PythonApiKeyRequest>()?;module.add_class::<PythonApiKeyOutput>()?;Ok(())
}
