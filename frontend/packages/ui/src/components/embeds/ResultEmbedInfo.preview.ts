const defaultProps = { icon: 'fence', label: 'Balcony: Yes', state: 'yes' as const };
export default defaultProps;
export const variants = {
  absent: { ...defaultProps, label: 'Balcony: No', state: 'no' as const },
  unknown: { ...defaultProps, label: 'Balcony: Unknown', state: 'unknown' as const },
  fact: { icon: 'euro', label: 'Warm rent: 850 EUR per month', value: '850', caption: 'Warm rent' },
};
