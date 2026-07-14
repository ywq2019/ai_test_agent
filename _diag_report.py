import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

async def main():
    from tools.database import async_session_maker, TestReport
    from sqlalchemy import select
    async with async_session_maker() as db:
        r = await db.execute(select(TestReport).order_by(TestReport.id.desc()).limit(5))
        rows = r.scalars().all()
        for row in rows:
            print(f"--- Report id={row.id} name={row.name} ---")
            details = json.loads(row.details) if isinstance(row.details, str) else (row.details or [])
            for d in details[:3]:
                shot = d.get("screenshot")
                print(f"  screenshot: {shot!r}")

asyncio.run(main())
