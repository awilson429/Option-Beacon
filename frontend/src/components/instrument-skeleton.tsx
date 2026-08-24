export function InstrumentSkeleton() {
  return <article aria-label="Loading instrument" className="surface overflow-hidden p-5">
    <div className="flex justify-between"><div><div className="skeleton h-4 w-16"/><div className="skeleton mt-3 h-9 w-32"/></div><div className="skeleton h-7 w-20"/></div>
    <div className="mt-6 grid grid-cols-3 gap-3">{Array.from({length:6}).map((_,i)=><div className="skeleton h-14" key={i}/>)}</div>
    <div className="skeleton mt-6 h-44"/><div className="skeleton mt-4 h-40"/>
  </article>;
}
