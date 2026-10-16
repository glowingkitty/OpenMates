/** Generated model metadata with a real public poster and downloadable GLB. */
const posterUrl = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="160" height="120"%3E%3Crect width="160" height="120" fill="%237898b3"/%3E%3C/svg%3E';

const defaultProps = {
  embedId: '6bfe4822-f203-427e-92d2-e30fc1e6940d',
  data: {
    decodedContent: {
      prompt: 'A textured stone arch with moss and carved details',
      provider_model: 'hitem3dv2.1',
      posterUrl,
      modelUrl: '/preview-generated-model.glb',
    },
  },
  onClose: () => {},
};

export default defaultProps;

export const variants = {
  privateModel: {
    ...defaultProps,
    data: {
      decodedContent: {
        prompt: 'A textured stone arch with moss and carved details',
        provider_model: 'hitem3dv2.1',
        posterUrl,
        files: { master: { s3_key: 'encrypted-model.glb.enc' } },
      },
    },
  },
};
