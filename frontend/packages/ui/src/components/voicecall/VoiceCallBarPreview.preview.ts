export default {};
export const variants = {
  constrainedMedia:{withinHistory:true,historyHeight:400,realAudio:false,state:{
    mediaExpanded:true,displayedMedia:{embedId:'preview-generated-image',kind:'image',url:'/images/examples/group1.jpg'},
  }},
  idle:{ state:{inputIdle:true,billingActivity:{inputListening:false,processing:false}},realAudio:false },
  muted:{ state:{muted:true,billingActivity:{inputListening:false,processing:false}},realAudio:false },
  mutedWorking:{ state:{muted:true,billingActivity:{inputListening:false,processing:true}},realAudio:false },
  playback:{ state:{muted:true,assistantSpeaking:true,billingActivity:{inputListening:false,processing:false}} },
  connecting:{ state:{status:'connecting',activeElapsedSeconds:0},realAudio:false },
  error:{ state:{status:'error',error:'connection_lost'},realAudio:false },
  contextError:{ state:{status:'error',error:'context_too_large'},realAudio:false },
};
