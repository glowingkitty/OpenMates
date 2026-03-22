declare module '*.yml' {
  const content: any;
  export default content;
}

declare module '*.yaml' {
  const content: any;
  export default content;
}

declare module '*.svelte' {
  const component: any;
  export default component;
}
