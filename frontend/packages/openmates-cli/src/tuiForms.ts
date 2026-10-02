/** Terminal forms keep editing and confirmations inside the workspace. */
export type TuiFormField = {
  name: string;
  label: string;
  value: string;
  options?: string[];
  multiline?: boolean;
};

export type TuiForm = {
  kind: string;
  title: string;
  fields: TuiFormField[];
  fieldIndex: number;
  contextId?: string;
  error?: string;
  busy?: boolean;
};

export function formValue(form: TuiForm, name: string): string {
  return form.fields.find((field) => field.name === name)?.value ?? "";
}
