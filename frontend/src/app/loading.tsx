export default function Loading() {
  return (
    <main className="loading-screen" aria-label="正在加载工作台">
      <div className="loading-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p>正在准备工作台</p>
    </main>
  );
}
