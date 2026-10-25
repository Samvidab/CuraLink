/** The supplied CuraLink logo (public/CuraLinkLogo2.png), shown exactly as provided: square, not cropped or recoloured. */
export function Logo({ size = 40, className = '', decorative = false }: { size?: number; className?: string; decorative?: boolean }) {
  return <img src="/CuraLinkLogo2.png" width={size} height={size} alt={decorative ? '' : 'CuraLink logo'} className={`shrink-0 object-contain ${className}`} style={{ width: size, height: size }}/>
}
