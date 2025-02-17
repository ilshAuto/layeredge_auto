import asyncio
import sys
import time
from typing import Optional

import cloudscraper
import httpx
from loguru import logger

# 初始化日志记录
logger.remove()
logger.add(sys.stdout, format='<g>{time:YYYY-MM-DD HH:mm:ss:SSS}</g> | <c>{level}</c> | <level>{message}</level>')


class ScraperReq:
    def __init__(self, proxy: dict, header: dict):
        self.scraper = cloudscraper.create_scraper(browser={
            'browser': 'chrome',
            'platform': 'windows',
            'mobile': False,
        })
        self.proxy: dict = proxy
        self.header: dict = header

    def post_req(self, url, req_json, req_param):
        # logger.info(self.header)
        # logger.info(req_json)
        return self.scraper.post(url=url, headers=self.header, json=req_json, proxies=self.proxy, params=req_param)

    async def post_async(self, url, req_param=None, req_json=None):
        return await asyncio.to_thread(self.post_req, url, req_json, req_param)

    def get_req(self, url, req_param):
        return self.scraper.get(url=url, headers=self.header, params=req_param, proxies=self.proxy)

    async def get_async(self, url, req_param=None, req_json=None):
        return await asyncio.to_thread(self.get_req, url, req_param)


class LayerEdge:
    def __init__(self, index: int, proxy: str, headers: dict, mnemonic: str):
        proxies = {
            'http': proxy,
            'https': proxy,
        }
        self.index: Optional[int] = index
        self.proxy = proxy
        self.scrape: Optional[ScraperReq] = ScraperReq(proxies, headers)
        self.address: Optional[str] = None
        self.mnemonic = mnemonic

    async def check_proxy(self):
        try:
            res = await self.scrape.get_async('http://ip-api.com/json')
            logger.info(f'{self.index}, {self.proxy} 代理检测成功: {res.text}')
        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} 代理检测失败: {e}')
            return False
        return True

    async def loop_task(self):
        while True:
            proxy_flag = await self.check_proxy()
            if not proxy_flag:
                logger.info(f'{self.index}, {self.proxy} 代理检测失败，睡眠3h重试')
                await asyncio.sleep(10800)
                continue
            address_flag = await self.get_address()
            if not address_flag:
                logger.info(f'{self.index}, {self.proxy} 钱包地址获取失败，睡眠30秒重试')
                await asyncio.sleep(30)
                continue

            await self.start_node()

    async def get_address(self):
        wallet_address_payload = {
            'mnemonic': self.mnemonic
        }
        address = ''
        for i in range(3):
            try:
                address_res = await httpx.AsyncClient().post('http://127.0.0.1:3666/api/wallet_address',
                                                             json=wallet_address_payload)
                address = address_res.json()['data']['address']
                logger.info(f'{self.index}, {self.proxy}, 获取钱包地址：{address}')
                self.address = address
                return True
            except Exception as e:
                print(e)
                await asyncio.sleep(30)
        if address == '':
            return False

    async def start_node(self):
        try:
            # 构建签名payload
            timestamp = int(time.time() * 1000)  # 获取当前时间戳
            sign_payload = {
                'mnemonic': self.mnemonic,
                'payload': f'Node activation request for {self.address} at {timestamp}',
                'proxy': self.proxy
            }
            # print(sign_payload)
            # 请求签名
            try:
                sign_res = await httpx.AsyncClient().post('http://127.0.0.1:3666/api/sign', json=sign_payload)
            except Exception as e:
                logger.error(f'{self.index}, {self.proxy} 签名服务请求失败，{e}')
                await asyncio.sleep(20)
                return
            # if not sign_res:
            #     logger.error(f'{self.index}, {self.proxy} 签名失败: {sign_res.text}')
            #     return
            # print(sign_res.text)
            signature = sign_res.json()['signature']
            logger.info(f'{self.index}, {self.proxy} {self.address} 签名结果：{signature}')

            # 启动节点
            start_node_payload = {
                "sign": signature,
                "timestamp": timestamp
            }
            start_node_url = f'https://referralapi.layeredge.io/api/light-node/node-action/{self.address}/start'
            start_node_res = await self.scrape.post_async(start_node_url, req_json=start_node_payload)
            # logger.info(f'{self.index}, {self.proxy} {self.address}节点启动成功: {start_node_res.text}')
            if 'can not start multiple light node' in start_node_res.text or 'node action executed successfully' in start_node_res.text:
                logger.info(f'{self.index}, {self.proxy} {self.address} 节点启动成功')
                # 启动轮询
                await self.poll_node_info()

        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} {self.address}节点操作失败: {e}')
            await asyncio.sleep(30)

    async def check_node_status(self):
        """检查节点状态"""
        try:
            status_url = f'https://referralapi.layeredge.io/api/light-node/node-status/{self.address}'
            status_res = await self.scrape.get_async(status_url)
            status_data = status_res.json()['data']
            start_timestamp = status_data.get('startTimestamp')

            if not start_timestamp:
                logger.error(f'{self.index}, {self.proxy} {self.address} 节点未启动')
                return False

            logger.info(f'{self.index}, {self.proxy} {self.address} 节点启动时间: {start_timestamp}')
            return True
        except Exception as e:
            logger.debug(f'{self.index}, {self.proxy} {self.address} 获取节点状态失败: {e}')
            return True

    async def poll_node_info(self):
        """轮询节点相关接口"""
        while True:
            epoch = 0
            try:
                # 检查钱包详情
                wallet_detail_url = f'https://referralapi.layeredge.io/api/referral/wallet-details/{self.address}'
                detail_res = await self.scrape.get_async(wallet_detail_url)
                detail_data = detail_res.json()['data']

                daily_streak = detail_data.get('dailyStreak', 0)
                node_points = detail_data.get('nodePoints', 0)
                last_claimed = detail_data.get('lastClaimed')

                logger.info(f'{self.index}, {self.proxy} {self.address} 钱包详情: '
                            f'连续签到: {daily_streak}, 节点积分: {node_points}, '
                            f'上次签到时间: {last_claimed}')

                # 检查是否需要签到
                need_claim = await self.check_claim_status(last_claimed)
                if need_claim:
                    await self.claim_daily()

                # 检查节点状态
                if not await self.check_node_status():
                    logger.debug(f'{self.index}, {self.proxy}, {self.address} 节点未启动，返回')
                    return

                # 请求排行榜数据
                try:
                    # 节点排行榜
                    node_leaderboard_url = 'https://referralapi.layeredge.io/api/light-node/node-leaderboard'
                    await self.scrape.get_async(node_leaderboard_url, req_param={'offset': 0, 'limit': 50})

                    # 推荐排行榜
                    referral_leaderboard_url = 'https://referralapi.layeredge.io/api/referral/leaderboard'
                    await self.scrape.get_async(referral_leaderboard_url, req_param={'offset': 0, 'limit': 100})


                except Exception as e:
                    logger.error(f'{self.index}, {self.proxy} {self.address} 请求排行榜数据失败: {e}')

                if not await self.check_node_status():
                    logger.debug(f'{self.index}, {self.proxy}, {self.address} 节点未启动，返回')
                    return
                    # 一组请求完成后休眠1分钟
                logger.success(f'{self.index}, {self.proxy} {self.address} 完成一轮轮询，睡眠60s')
                await asyncio.sleep(60)

                epoch = epoch + 1
                if epoch >= 100:
                    await self.stop_node()

            except Exception as e:
                logger.error(f'{self.index}, {self.proxy} {self.address} 轮询节点信息失败: {e}')
                await asyncio.sleep(2)
                continue

    async def check_claim_status(self, last_claimed):
        """检查是否需要签到"""
        if not last_claimed:
            logger.info(f'{self.index}, {self.proxy} {self.address} 从未签到，准备首次签到')
            return True

        try:
            last_claimed_time = time.mktime(time.strptime(last_claimed.split('.')[0], "%Y-%m-%dT%H:%M:%S"))
            current_time = time.time()

            time_diff = current_time - last_claimed_time
            if time_diff >= 24 * 3600:  # 超过24小时
                logger.info(f'{self.index}, {self.proxy} {self.address} 距离上次签到已超过24小时，准备签到')
                return True
        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} {self.address} 计算签到时间差异出错: {e}')

        return False

    async def claim_daily(self):
        """
        签到方法
        """
        try:
            # 构建签名payload
            timestamp = int(time.time() * 1000)
            sign_payload = {
                'mnemonic': self.mnemonic,
                'payload': f'I am claiming my daily node point for {self.address} at {timestamp}',
                'proxy': self.proxy
            }

            # 请求签名
            try:
                sign_res = await httpx.AsyncClient().post('http://127.0.0.1:3666/api/sign', json=sign_payload)
            except Exception as e:
                logger.error(f'{self.index}, {self.proxy} {self.address} 签到签名请求失败: {e}')
                return

            signature = sign_res.json()['signature']
            logger.info(f'{self.index}, {self.proxy} {self.address} 签到签名结果: {signature}')

            # 发送签到请求
            claim_url = 'https://referralapi.layeredge.io/api/light-node/claim-node-points'
            claim_payload = {
                "walletAddress": self.address,
                "timestamp": timestamp,
                "sign": signature
            }

            claim_res = await self.scrape.post_async(claim_url, req_json=claim_payload)
            if 'node points claimed successfully' in claim_res.text:
                logger.info(f'{self.index}, {self.proxy} {self.address} 签到成功')
            else:
                logger.error(f'{self.index}, {self.proxy} {self.address} 签到失败: {claim_res.text}')

        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} {self.address} 签到过程出错: {e}')

    async def stop_node(self):
        timestamp = int(time.time() * 1000)  # 获取当前时间戳
        sign_payload = {
            'mnemonic': self.mnemonic,
            'payload': f'Node deactivation request for {self.address} at {timestamp}',
            'proxy': self.proxy
        }
        # print(sign_payload)
        # 请求签名
        try:
            sign_res = await httpx.AsyncClient().post('http://127.0.0.1:3666/api/sign', json=sign_payload)
        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} 停止节点签名服务请求失败，{e}')
            await asyncio.sleep(20)
            return
        pass
        signature = sign_res.json()['signature']
        logger.info(f'{self.index}, {self.proxy} {self.address} 停止节点签名结果：{signature}')

        # 启动节点
        start_node_payload = {
            "sign": signature,
            "timestamp": timestamp
        }
        stop_node_url = f'https://referralapi.layeredge.io/api/light-node/node-action/{self.address}/stop'
        try:
            stop_node_res = await self.scrape.post_async(stop_node_url, req_json=start_node_payload)
            logger.info(f'{self.index}, {self.proxy} {self.address} 停止节点结果：{stop_node_res.text}')
        except Exception as e:
            logger.error(f'{self.index}, {self.proxy} {self.address} 停止节点失败：{e}')


async def run(acc: dict):
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://dashboard.layeredge.io',
        'referer': 'https://dashboard.layeredge.io',
    }
    layer = LayerEdge(acc['index'], acc['proxy'], headers, acc['mnemonic'])
    await layer.loop_task()


async def main():
    accs = []
    with open('./acc', 'r', encoding='utf-8') as file:
        for line in file.readlines():
            parts = line.strip().split('----')
            acc = {
                'mnemonic': parts[0],
                'proxy': parts[1]
            }
            accs.append(acc)
    tasks = []
    for index, acc in enumerate(accs):
        acc['index'] = index
        task = run(acc)
        tasks.append(task)

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    logger.info('🚀 [ILSH] layeredge v1.0 | Airdrop Campaign Live')
    logger.info('🌐 ILSH Community: t.me/ilsh_auto')
    logger.info('🐦 X(Twitter): https://x.com/hashlmBrian')
    logger.info('☕ Pay me Coffe：USDT（TRC20）:TAiGnbo2isJYvPmNuJ4t5kAyvZPvAmBLch')
    asyncio.run(main())
