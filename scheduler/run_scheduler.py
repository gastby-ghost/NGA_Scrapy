import subprocess
import time
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pytz import timezone

def run_spider():
    subprocess.run(["scrapy", "crawl", "nga"], check=True)

if __name__ == '__main__':
    tz = timezone('Asia/Shanghai')
    scheduler = BackgroundScheduler(timezone=tz)
    
    scheduler.add_job(
        run_spider,
        'interval',
        minutes=30,
        next_run_time=datetime.now(tz),
    )
    
    scheduler.start()
    print("启动定时调度器，按 Ctrl+C 退出")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("调度器已关闭")
