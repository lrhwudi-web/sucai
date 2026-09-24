interface BrandMarkProps {
  className?: string;
  subtitle?: string;
}

export function BrandMark({ className = "", subtitle }: BrandMarkProps) {
  return (
    <span className={`brand-mark ${className}`.trim()}>
      <span className="brand-mark-logo" aria-hidden="true">
        <img src="/assets/kairay-golf-logo.png?v=4bf743d2" alt="" />
      </span>
      <span className="brand-mark-copy">
        <strong>KAIRAY GOLF</strong>
        {subtitle && <small>{subtitle}</small>}
      </span>
    </span>
  );
}
