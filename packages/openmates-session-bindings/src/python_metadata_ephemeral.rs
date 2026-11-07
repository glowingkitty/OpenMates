use crate::{BindingError,metadata_ephemeral::*};
use pyo3::{prelude::*,exceptions::PyRuntimeError};
fn error(value:BindingError)->PyErr{PyRuntimeError::new_err(value.json())}
#[pyclass(name="NativeMetadataAuthentication",module="openmates._native")]
struct PythonMetadataAuthentication{handle:MetadataAuthenticationHandle}
#[pymethods]
impl PythonMetadataAuthentication {
    #[new]
    fn new(input_json:String)->PyResult<Self>{MetadataAuthenticationHandle::new(input_json,openmates_sdk::ClientIdentity::Pip).map(|handle|Self{handle}).map_err(error)}
    fn authenticate<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{
        let handle=self.handle.clone();crate::python_future::future_into_py(py,async move{Ok(PythonMetadataClient{handle:handle.authenticate().await.map_err(error)?})})
    }
    fn credential_snapshot_json(&self)->PyResult<String>{self.handle.credential_snapshot_json().map_err(error)}
    fn cancel(&self){self.handle.cancel();}
    fn cancel_and_drain<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{let handle=self.handle.clone();crate::python_future::future_into_py(py,async move{handle.cancel_and_drain().await.map_err(error)})}
}
#[pyclass(name="NativeEphemeralMetadataClient",module="openmates._native")]
struct PythonMetadataClient{handle:MetadataClientHandle}
#[pymethods]
impl PythonMetadataClient {
    fn prepare_initial_sync(&self)->PyResult<PythonMetadataStartup>{self.handle.prepare_initial_sync().map(|handle|PythonMetadataStartup{handle}).map_err(error)}
    fn credential_snapshot_json(&self)->PyResult<String>{self.handle.credential_snapshot_json().map_err(error)}
    fn close<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{let handle=self.handle.clone();crate::python_future::future_into_py(py,async move{handle.close().await.map_err(error)})}
}
#[pyclass(name="NativeEphemeralMetadataStartup",module="openmates._native")]
struct PythonMetadataStartup{handle:MetadataStartupHandle}
#[pymethods]
impl PythonMetadataStartup {
    fn run<'py>(&self,py:Python<'py>)->PyResult<Bound<'py,PyAny>>{
        let pending=self.handle.take().map_err(error)?;let control=self.handle.control();
        crate::python_future::future_into_py(py,async move{Ok(PythonMetadataSnapshot{handle:MetadataSnapshotHandle{inner:pending.run().await.map_err(|e|error(e.into()))?,_control:control}})})
    }
    fn cancel(&self){self.handle.cancel();}
}
#[pyclass(name="NativeEphemeralMetadataSnapshot",module="openmates._native")]
struct PythonMetadataSnapshot{handle:MetadataSnapshotHandle}
#[pymethods]
impl PythonMetadataSnapshot {
    fn received_metadata_count(&self,client:&PythonMetadataClient)->PyResult<u32>{self.handle.received_metadata_count(&client.handle).map_err(error)}
    fn cancel(&self){self.handle.cancel();}
}
pub(crate) fn register(module:&Bound<'_,PyModule>)->PyResult<()>{
    module.add_class::<PythonMetadataAuthentication>()?;module.add_class::<PythonMetadataClient>()?;
    module.add_class::<PythonMetadataStartup>()?;module.add_class::<PythonMetadataSnapshot>()?;Ok(())
}
