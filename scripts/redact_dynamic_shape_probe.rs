// Task-private addition to the unchanged licensed Rust host. Public LiteRT C
// ABI only: no SDK-private pointers, binary edits, conversion, or inference.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct ProbeLayout {
    bits: u32,
    dimensions: [i32; 8],
    strides: [u32; 8],
}
impl ProbeLayout {
    fn shape(&self) -> Res<Vec<i32>> {
        let rank = (self.bits & 127) as usize;
        if rank > 8 { return Err("probe-layout-rank-invalid"); }
        Ok(self.dimensions[..rank].to_vec())
    }
}
type ProbePtr = *mut c_void;
type ProbeDestroy = unsafe extern "C" fn(ProbePtr);
struct ProbeObjects {
    environment: ProbePtr,
    model: ProbePtr,
    options: ProbePtr,
    compiled: ProbePtr,
    destroy_environment: ProbeDestroy,
    destroy_model: ProbeDestroy,
    destroy_options: ProbeDestroy,
    destroy_compiled: ProbeDestroy,
}
impl Drop for ProbeObjects {
    fn drop(&mut self) {
        unsafe {
            if !self.compiled.is_null() { (self.destroy_compiled)(self.compiled); }
            if !self.options.is_null() { (self.destroy_options)(self.options); }
            if !self.model.is_null() { (self.destroy_model)(self.model); }
            if !self.environment.is_null() { (self.destroy_environment)(self.environment); }
        }
    }
}
unsafe extern "C" fn probe_destroy_toml(value: ProbePtr) {
    if !value.is_null() { drop(unsafe { CString::from_raw(value.cast()) }); }
}
struct ProbeReport<'a> {
    output: &'a Path,
    meta: &'a RunMeta,
    events: Vec<String>,
}
impl ProbeReport<'_> {
    fn persist(&self, state: &str, feasibility: &str) -> Res<()> {
        save(self.output, state, self.meta, &[])?;
        let old = fs::read_to_string(self.output).map_err(|_| "probe-read-receipt-failed")?;
        // The inherited benchmark writer describes an input-reading flow.
        // This allocation-only probe returns before the input file is opened.
        if old.matches("\"input_read_after_seal\":true").count() != 1 {
            return Err("probe-inherited-input-proof-anchor");
        }
        let old = old.replace("\"input_read_after_seal\":true", "\"input_read\":false");
        let fields = format!("\"dynamic_shape_probe\":{{\"feasibility\":{},\"public_api_only\":true,\"target_shape\":[1,64],\"sdk_licensed_before_probe\":true,\"network_sealed_before_probe\":true,\"input_read\":false,\"inference_executed\":false,\"events\":[{}]}},\"cases\":[]", json_string(feasibility), self.events.join(","));
        if old.matches("\"cases\":[]").count() != 1 { return Err("probe-receipt-anchor"); }
        let next = old.replace("\"cases\":[]", &fields);
        let temp = self.output.with_extension("probe.tmp");
        fs::write(&temp, next).map_err(|_| "probe-write-receipt-failed")?;
        fs::rename(temp, self.output).map_err(|_| "probe-rename-receipt-failed")?;
        Ok(())
    }
    fn note(&mut self, operation: &str, details: &str) -> Res<()> {
        self.events.push(format!("{{\"operation\":{},\"details\":{}}}", json_string(operation), details));
        self.persist("running", "in-progress")
    }
    fn status(&mut self, operation: &str, status: i32) -> Res<bool> {
        self.events.push(format!("{{\"operation\":{},\"status\":{}}}", json_string(operation), status));
        self.persist("running", "in-progress")?;
        Ok(status == 0)
    }
    fn finish(&mut self, feasibility: &str) -> Res<bool> {
        self.persist("complete", feasibility)?;
        Ok(true) // The generated host returns before reading synthetic input.
    }
}

fn dynamic_shape_probe(native: &Path, directory: &Path, output: &Path, meta: &RunMeta) -> Res<bool> {
    if LICENSE_VALID.load(Ordering::Relaxed) == 0 || meta.network.is_none() {
        return Err("probe-requires-real-license-and-network-seal");
    }
    if std::mem::size_of::<ProbeLayout>() != 68 { return Err("probe-layout-abi-size"); }
    let lib = library(native.join("libLiteRt.so").to_str().ok_or("probe-runtime-path")?, 2 | 4)?;
    macro_rules! api {
        ($name:literal, $type:ty) => { unsafe { symbol::<$type>(lib, $name)? } };
    }
    let mut report = ProbeReport { output, meta, events: Vec::new() };
    macro_rules! step {
        ($name:expr, $call:expr) => {{
            report.note($name, "\"call-started\"")?;
            let result = unsafe { $call };
            if !report.status($name, result)? { return report.finish("public-api-rejected"); }
        }};
    }
    let create_environment = api!("LiteRtCreateEnvironment", unsafe extern "C" fn(i32, *const c_void, *mut ProbePtr) -> i32);
    let create_model = api!("LiteRtCreateModelFromFile", unsafe extern "C" fn(ProbePtr, *const c_char, *mut ProbePtr) -> i32);
    let create_options = api!("LiteRtCreateOptions", unsafe extern "C" fn(*mut ProbePtr) -> i32);
    let set_hardware = api!("LiteRtSetOptionsHardwareAccelerators", unsafe extern "C" fn(ProbePtr, i32) -> i32);
    let create_opaque = api!("LiteRtCreateOpaqueOptions", unsafe extern "C" fn(*const c_char, ProbePtr, ProbeDestroy, *mut ProbePtr) -> i32);
    let add_opaque = api!("LiteRtAddOpaqueOptions", unsafe extern "C" fn(ProbePtr, ProbePtr) -> i32);
    let destroy_opaque = api!("LiteRtDestroyOpaqueOptions", ProbeDestroy);
    let create_compiled = api!("LiteRtCreateCompiledModel", unsafe extern "C" fn(ProbePtr, ProbePtr, ProbePtr, *mut ProbePtr) -> i32);
    let get_signature = api!("LiteRtGetModelSignature", unsafe extern "C" fn(ProbePtr, usize, *mut ProbePtr) -> i32);
    let num_inputs = api!("LiteRtGetNumSignatureInputs", unsafe extern "C" fn(ProbePtr, *mut usize) -> i32);
    let num_outputs = api!("LiteRtGetNumSignatureOutputs", unsafe extern "C" fn(ProbePtr, *mut usize) -> i32);
    let input_name = api!("LiteRtGetSignatureInputName", unsafe extern "C" fn(ProbePtr, usize, *mut *const c_char) -> i32);
    let input_layout = api!("LiteRtGetCompiledModelInputTensorLayout", unsafe extern "C" fn(ProbePtr, usize, usize, *mut ProbeLayout) -> i32);
    let output_layouts = api!("LiteRtGetCompiledModelOutputTensorLayouts", unsafe extern "C" fn(ProbePtr, usize, usize, *mut ProbeLayout, bool) -> i32);
    let resize = api!("LiteRtCompiledModelResizeInputTensorNonStrict", unsafe extern "C" fn(ProbePtr, usize, usize, *const i32, usize) -> i32);
    let input_requirements = api!("LiteRtGetCompiledModelInputBufferRequirements", unsafe extern "C" fn(ProbePtr, usize, usize, *mut ProbePtr) -> i32);
    let output_requirements = api!("LiteRtGetCompiledModelOutputBufferRequirements", unsafe extern "C" fn(ProbePtr, usize, usize, *mut ProbePtr) -> i32);
    let buffer_size = api!("LiteRtGetTensorBufferRequirementsBufferSize", unsafe extern "C" fn(ProbePtr, *mut usize) -> i32);
    let mut objects = ProbeObjects {
        environment: std::ptr::null_mut(), model: std::ptr::null_mut(),
        options: std::ptr::null_mut(), compiled: std::ptr::null_mut(),
        destroy_environment: api!("LiteRtDestroyEnvironment", ProbeDestroy),
        destroy_model: api!("LiteRtDestroyModel", ProbeDestroy),
        destroy_options: api!("LiteRtDestroyOptions", ProbeDestroy),
        destroy_compiled: api!("LiteRtDestroyCompiledModel", ProbeDestroy),
    };
    step!("LiteRtCreateEnvironment", create_environment(0, std::ptr::null(), &mut objects.environment));
    let file = CString::new(directory.join("redact.tflite").as_os_str().as_encoded_bytes()).map_err(|_| "probe-model-path")?;
    step!("LiteRtCreateModelFromFile", create_model(objects.environment, file.as_ptr(), &mut objects.model));
    step!("LiteRtCreateOptions", create_options(&mut objects.options));
    step!("LiteRtSetOptionsHardwareAccelerators(CPU)", set_hardware(objects.options, 1));
    for name in ["xnnpack", "cpu_options"] {
        let identifier = CString::new(name).map_err(|_| "probe-option-name")?;
        let data = CString::new("num_threads = 2\n").map_err(|_| "probe-thread-option")?.into_raw();
        let mut opaque = std::ptr::null_mut();
        let status = unsafe { create_opaque(identifier.as_ptr(), data.cast(), probe_destroy_toml, &mut opaque) };
        if status != 0 { unsafe { probe_destroy_toml(data.cast()); } }
        if !report.status("LiteRtCreateOpaqueOptions(two CPU threads)", status)? { return report.finish("public-api-rejected"); }
        let status = unsafe { add_opaque(objects.options, opaque) };
        if status != 0 { unsafe { destroy_opaque(opaque); } }
        if !report.status("LiteRtAddOpaqueOptions", status)? { return report.finish("public-api-rejected"); }
    }
    step!("LiteRtCreateCompiledModel", create_compiled(objects.environment, objects.model, objects.options, &mut objects.compiled));
    let mut signature = std::ptr::null_mut();
    step!("LiteRtGetModelSignature", get_signature(objects.model, 0, &mut signature));
    let (mut inputs, mut outputs) = (0, 0);
    step!("LiteRtGetNumSignatureInputs", num_inputs(signature, &mut inputs));
    step!("LiteRtGetNumSignatureOutputs", num_outputs(signature, &mut outputs));
    if inputs == 0 || inputs > 4 || outputs != 1 { return Err("probe-unexpected-signature-arity"); }
    for index in 0..inputs {
        let mut name = std::ptr::null();
        step!("LiteRtGetSignatureInputName", input_name(signature, index, &mut name));
        if name.is_null() { return Err("probe-null-input-name"); }
        let name = unsafe { CStr::from_ptr(name) }.to_str().map_err(|_| "probe-input-name-utf8")?;
        let mut layout = ProbeLayout::default();
        step!("LiteRtGetCompiledModelInputTensorLayout(before)", input_layout(objects.compiled, 0, index, &mut layout));
        let shape = layout.shape()?;
        report.note("original-input", &format!("{{\"index\":{},\"name\":{},\"shape\":{:?}}}", index, json_string(name), shape))?;
        if shape != [1, 256] { return Err("probe-unexpected-original-input-shape"); }
    }
    let mut layouts = vec![ProbeLayout::default(); outputs];
    step!("LiteRtGetCompiledModelOutputTensorLayouts(before)", output_layouts(objects.compiled, 0, outputs, layouts.as_mut_ptr(), false));
    report.note("original-output", &format!("{:?}", layouts[0].shape()?))?;
    let dims = [1, 64];
    for index in 0..inputs {
        report.note("resize-input-index", &index.to_string())?;
        step!("LiteRtCompiledModelResizeInputTensorNonStrict([1,64])", resize(objects.compiled, 0, index, dims.as_ptr(), dims.len()));
    }
    // This documented update_allocation=true call genuinely propagates input
    // shapes through graph allocation. A fixed reshape/position constant fails
    // here; report the precise status and retained native stderr, then stop.
    step!("LiteRtGetCompiledModelOutputTensorLayouts(update_allocation=true)", output_layouts(objects.compiled, 0, outputs, layouts.as_mut_ptr(), true));
    let shape = layouts[0].shape()?;
    report.note("resized-output", &format!("{:?}", shape))?;
    if shape.len() != 3 || shape[0] != 1 || shape[1] != 64 || shape[2] <= 0 {
        return report.finish("output-did-not-resize-to-64");
    }
    for index in 0..inputs {
        let mut layout = ProbeLayout::default();
        step!("LiteRtGetCompiledModelInputTensorLayout(after)", input_layout(objects.compiled, 0, index, &mut layout));
        if layout.shape()? != dims { return report.finish("input-layout-did-not-resize-to-64"); }
        let mut requirements = std::ptr::null_mut();
        step!("LiteRtGetCompiledModelInputBufferRequirements(after)", input_requirements(objects.compiled, 0, index, &mut requirements));
        let mut size = 0;
        step!("LiteRtGetTensorBufferRequirementsBufferSize(input)", buffer_size(requirements, &mut size));
        report.note("resized-input-buffer-bytes", &format!("{{\"index\":{},\"bytes\":{}}}", index, size))?;
    }
    let mut requirements = std::ptr::null_mut();
    step!("LiteRtGetCompiledModelOutputBufferRequirements(after)", output_requirements(objects.compiled, 0, 0, &mut requirements));
    let mut size = 0;
    step!("LiteRtGetTensorBufferRequirementsBufferSize(output)", buffer_size(requirements, &mut size));
    report.note("resized-output-buffer-bytes", &size.to_string())?;
    report.finish("allocation-and-output-shape-64-succeeded-logits-not-run")
}
