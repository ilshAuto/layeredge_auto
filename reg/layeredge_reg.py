import asyncio
import random
import sys
import time
from typing import Optional

import cloudscraper
import httpx
from loguru import logger
import aiofiles

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


class LayerEdgeReg:
    def __init__(self, index: int, proxy: str, headers: dict, mnemonic: str, invite: str, mode: int):
        proxies = {
            'http': proxy,
            'https': proxy,
        }
        self.index: Optional[int] = index
        self.proxy = proxy
        self.scrape: Optional[ScraperReq] = ScraperReq(proxies, headers)
        self.mnemonic = mnemonic
        self.invite = invite
        self.address: Optional[str] = ''
        self.mode = mode

    @staticmethod
    async def save_to_file(content: str, filename: str = '../invite_codes') -> bool:
        """
        异步保存内容到文件
        :param content: 要保存的内容
        :param filename: 文件名，默认为 '../invite_codes'
        :return: 是否保存成功
        """
        try:
            async with asyncio.Lock():
                async with aiofiles.open(filename, 'a', encoding='utf-8') as f:
                    await f.write(f'{content}\n')
            return True
        except Exception as e:
            logger.error(f'文件写入失败: {e}')
            return False

    async def start(self):
        wallet_address_payload = {
            'mnemonic': self.mnemonic
        }
        address = ''
        for i in range(3):
            try:
                address_res = await httpx.AsyncClient().post('http://127.0.0.1:3666/api/wallet_address',
                                                             json=wallet_address_payload, timeout=30)

                address = address_res.json()['data']['address']
            except Exception as e:
                time.sleep(30)
        if address == '':
            return
        print(address)
        self.address = address
        url = f'https://referralapi.layeredge.io/api/referral/wallet-details/{address}'
        for i in range(3):
            try:
                detail_res = await self.scrape.get_async(url)
                print(detail_res.text)
            except Exception as e:
                logger.error(f'{self.index}, {address}, wallet-detail获取失败：{e}')
                return
            if 'user not found' in detail_res.text:
                logger.info(f'{self.index}, {address} 尚未注册，将开始注册。')
            elif 'wallet referral points' in detail_res.text:
                logger.info(f'{self.index}, {address} 已经注册')
                if self.mode == 1:
                    referral_code = detail_res.json()['data']['referralCode']
                    logger.info(f'{self.index}, {address} 开始记录邀请码到invite_codes')
                    content = referral_code
                    if await self.save_to_file(content):
                        logger.success(f'{self.index}, {address} 账号的邀请码: {referral_code} 记录成功')
                        return True
                    else:
                        logger.error(f'{self.index}, {address} 邀请码记录失败，将重试')
                        continue
                else:
                    return True

            else:
                logger.error(f'{self.index}, {address}, 出现未知响应：{detail_res.text}')

            for i in range(3):

                try:
                    verify_code_url = 'https://referralapi.layeredge.io/api/referral/verify-referral-code'
                    payload = {'invite_code': self.invite}
                    verify_res = await self.scrape.post_async(verify_code_url, req_json=payload, req_param=None)
                    if 'invite code is valid' in verify_res.text:
                        logger.info(f'{self.index}, {address}, 验证码：{self.invite}验证成功')
                except Exception as e:
                    logger.error(f'{self.index}, {address}, 注册时邀请码: {self.invite}, 验证失败, {e}, 将重试')
                    continue
                reg_url = f'https://referralapi.layeredge.io/api/referral/register-wallet/{self.invite}'
                reg_payload = {"walletAddress": self.address}
                reg_res = await self.scrape.post_async(reg_url, req_json=reg_payload, req_param=None)
                try:
                    if 'registered wallet address successfully' in reg_res.text:
                        logger.info(f'{self.index}, {address}, 注册成功')
                        if self.mode == 1:
                            referral_code = reg_res.json()['data']['referralCode']
                            logger.info(f'{self.index}, {address} 开始记录邀请码到invite_codes')
                            content = referral_code
                            if await self.save_to_file(content):
                                logger.success(f'{self.index}, {address} 账号的邀请码: {referral_code} 记录成功')
                                return True
                            else:
                                logger.error(f'{self.index}, {address} 邀请码记录失败，将重试')
                                break
                        else:
                            return True
                    else:
                        logger.error(f'{self.index}, {address}, 账号注册失败响应：{reg_res.text}，将重试')
                except Exception as e:
                    logger.error(f'{self.index}, {address}, 账号注册失败，将重试：{e}')


async def run(acc: dict):
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://dashboard.layeredge.io',
        'referer': 'https://dashboard.layeredge.io',
    }
    layer = LayerEdgeReg(acc.get('index'), acc.get('proxy'), headers, acc.get('mnemonic'), acc.get('invite'),
                         int(acc.get('mode')))
    reg_flag = await layer.start()
    if reg_flag:
        content = f"{acc.get('mnemonic')}----{acc.get('proxy')}"
        async with asyncio.Lock():
            async with aiofiles.open('../acc', 'a', encoding='utf-8') as f:
                await f.write(f'{content}\n')
        return True
    pass


async def main(mode: int):
    """
    !!! 修改你的主号邀请码 !!!
    """
    accs = []
    if mode == 1:
        print(f'mode为{mode}, 将注册主号')
        with open('./main_acc', 'r', encoding='utf-8') as file:
            for line in file.readlines():
                mnemonic, proxy = line.strip().split('----')

                main_acc_invite = '1PAzyeIu'
                acc = {
                    'index': 0,
                    'mnemonic': mnemonic,
                    'proxy': proxy,
                    'invite': main_acc_invite,
                    'mode': mode
                }
                accs.append(acc)
    elif mode == 2:
        print(f'mode为{mode}, 将注册受邀者')
        # 读取邀请码并去重
        invite_codes_set = set()
        try:
            with open('../invite_codes', 'r', encoding='utf-8') as file:
                for line in file.readlines():
                    invite_code = line.strip()
                    if invite_code:  # 确保不添加空行
                        invite_codes_set.add(invite_code)
        except FileNotFoundError:
            logger.error('invite_codes文件不存在，请先运行mode 1生成邀请码，或自行填写')
            return

        # 转换为列表以支持random.choice
        invite_codes = list(invite_codes_set)

        if not invite_codes:
            logger.error('没有可用的邀请码，请先运行mode 1生成邀请码 或自行填写')
            return

        # 读取待注册账号
        with open('./invitees_acc', 'r', encoding='utf-8') as file:
            for line in file.readlines():
                if not line.strip():  # 跳过空行
                    continue
                try:
                    mnemonic, proxy = line.strip().split('----')
                    invite = random.choice(invite_codes)  # 随机选择一个邀请码
                    acc = {
                        'index': 0,
                        'mnemonic': mnemonic,
                        'proxy': proxy,
                        'invite': invite,
                        'mode': mode
                    }
                    accs.append(acc)
                except ValueError:
                    logger.error(f'无效的账号格式: {line.strip()}')
                    continue
    else:
        logger.error('请选择正确的模式：1 或 2')
        return

    tasks = []
    for acc in accs:
        tasks.append(run(acc))
    await asyncio.gather(*tasks)


if __name__ == '__main__':
    logger.debug('🚀 [ILSH] layeredge REG v1.0 | Airdrop Campaign Live')
    logger.debug('🌐 ILSH Community 电报频道: t.me/ilsh_auto')
    logger.debug('🐦 X(Twitter) 推特: https://x.com/hashlmBrian')
    logger.debug('☕ Pay me Coffe USDT（TRC20）:TAiGnbo2isJYvPmNuJ4t5kAyvZPvAmBLch')
    print('-------运行说明--------')
    print('----------------------')
    print(
        '输入数字选择运行的模式，1：运行主号(main_acc文件)，会生成邀请码(！！在代码中修改你的主号邀请码！！),'
        '\n 2：运行受邀用户(invitees_acc文件)，会随机使用main_acc生成的邀请码(invite_codes文件)')
    print('----------------------')
    mode = input('输入数字：')
    # mode = 1
    asyncio.run(main(int(mode)))
