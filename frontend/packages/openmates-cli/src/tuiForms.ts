/** Terminal forms keep editing and confirmations inside the workspace. */
export type TuiFormField = {
  name: string;
  label: string;
  value: string;
  options?: string[];
  multiline?: boolean;
  /** Sensitive values are never echoed in the terminal frame. */
  secret?: boolean;
  /** Schema metadata lets the terminal editor explain and validate typed inputs. */
  valueType?: "string" | "number" | "integer" | "boolean" | "object" | "array";
  required?: boolean;
  minimum?: number;
  maximum?: number;
  format?: string;
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
