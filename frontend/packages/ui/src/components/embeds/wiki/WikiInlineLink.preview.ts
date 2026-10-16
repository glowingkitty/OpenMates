const defaultProps = { wikiTitle: 'Ada_Lovelace', displayText: 'Ada Lovelace', language: 'en' };
export default defaultProps;
export const variants = {
  wrongName: { ...defaultProps, displayText: 'Einstein', wikiTitle: 'Albert_Einstein' },
  disambiguation: { displayText: 'Mercury', wikiTitle: 'Mercury_(planet)', language: 'en' },
};
