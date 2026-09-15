import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** Cartão base reutilizado em todas as telas -- mesmo visual (borda +
 * fundo + raio) usado no preview original de App.tsx, agora centralizado
 * em vez de repetido em cada tela nova. */
export function Card({ title, icon, children, className = "" }: CardProps) {
  return (
    <div className={`rounded-xl border border-neutral-800 bg-neutral-900 p-5 ${className}`}>
      {title && (
        <div className="mb-3 flex items-center gap-2">
          {icon}
          <span className="font-medium">{title}</span>
        </div>
      )}
      {children}
    </div>
  );
}
