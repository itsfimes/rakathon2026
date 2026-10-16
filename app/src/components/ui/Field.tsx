import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'

export function Field({ id, label, children }: { readonly id: string; readonly label: string; readonly children: ReactNode }) {
  return <div className="field"><label className="label" htmlFor={id}>{label}</label>{children}</div>
}

export function Input(props: Omit<InputHTMLAttributes<HTMLInputElement>, 'className'>) {
  return <input className="input" {...props} />
}

export function Select(props: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className'>) {
  return <select className="select" {...props} />
}
