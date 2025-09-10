from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
import aiohttp
import json
import asyncio
from urllib.parse import quote, urljoin
import re

@register("netdisk_search", "deepseekR1", "网盘资源搜索插件", "1.0.0")
class NetdiskSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_url = "https://so.252035.xyz/api/search"
        self.debug_mode = True
        # 网盘域名映射
        self.cloud_domains = {
            'baidu': 'https://pan.baidu.com/',
            'aliyun': 'https://www.alipan.com/',
            'quark': 'https://pan.quark.cn/',
            'xunlei': 'https://pan.xunlei.com/',
            '115': 'https://115.com/',
            'uc': 'https://drive.uc.cn/',
            'tianyi': 'https://cloud.189.cn/',
            'mobile': 'https://caiyun.139.com/'
        }

    async def initialize(self):
        logger.info("网盘资源搜索插件已加载")

    @filter.command("search", "搜索网盘资源")
    async def netdisk_search(self, event: AstrMessageEvent):
        message_chain = event.get_messages()
        keyword = self.extract_keyword(message_chain)
        
        if not keyword:
            await event.send(event.plain_result("⚠️ 请提供搜索关键词，例如：/search 电影名"))
            return

        await event.send(event.plain_result(f"🔍 正在搜索: {keyword}..."))
        await self.perform_search(event, keyword)

    def extract_keyword(self, message_chain) -> str:
        keyword = ""
        for msg in message_chain:
            if hasattr(msg, 'text'):
                text = msg.text.strip()
                if text.startswith('/search'):
                    keyword = text.replace('/search', '').strip()
                elif text.startswith('搜索'):
                    keyword = text.replace('搜索', '').strip()
                else:
                    keyword = text
                
                if keyword:
                    break
        return keyword

    async def perform_search(self, event: AstrMessageEvent, keyword: str):
        try:
            results = await self.call_search_api(keyword)
            
            if not results:
                await event.send(event.plain_result("❌ 搜索失败或未找到结果"))
                return

            response = self.format_search_results(results, keyword)
            await event.send(event.plain_result(response))

        except Exception as e:
            logger.error(f"搜索失败: {str(e)}")
            await event.send(event.plain_result(f"❌ 搜索失败: {str(e)}"))

    async def call_search_api(self, keyword: str):
        """调用搜索API - 使用GET请求"""
        encoded_keyword = quote(keyword)
        url = f"{self.api_url}?kw={encoded_keyword}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                logger.debug(f"发送GET请求: {url}")
                
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API错误: HTTP {response.status} - {error_text[:200]}")
                        raise Exception(f"服务器错误: HTTP {response.status}")
                    
                    result = await response.json()
                    return result
                    
            except aiohttp.ClientError as e:
                logger.error(f"网络请求错误: {str(e)}")
                raise Exception(f"网络连接失败: {str(e)}")
            except asyncio.TimeoutError:
                logger.error("请求超时")
                raise Exception("搜索超时，请稍后重试")

    def format_search_results(self, data: dict, keyword: str) -> str:
        """格式化搜索结果"""
        if data.get("code") != 0:
            error_msg = data.get("message", "未知错误")
            return f"❌ API错误: {error_msg}"
        
        if not data.get("data"):
            return f"🔍 未找到与『{keyword}』相关的资源"
        
        result_data = data["data"]
        merged_results = result_data.get("merged_by_type", {})
        
        if not merged_results:
            return f"🔍 未找到与『{keyword}』相关的资源"

        lines = [
            f"🔍 搜索结果: {keyword}",
            f"📊 总共找到: {result_data.get('total', 0)} 条资源",
            "=" * 40
        ]

        # 统计各类型资源数量
        type_counts = {}
        total_results = 0
        
        for cloud_type, items in merged_results.items():
            if items and isinstance(items, list):
                count = len(items)
                type_counts[cloud_type] = count
                total_results += count

        if type_counts:
            lines.append("📁 资源类型分布:")
            for cloud_type, count in type_counts.items():
                lines.append(f"  • {self.get_type_name(cloud_type)}: {count}条")
            lines.append("")

        # 显示前几个资源的详细信息
        displayed_count = 0
        max_display = 8  # 减少显示数量以确保完整链接

        # 按资源类型排序显示
        preferred_order = ['quark', 'aliyun', 'baidu', '115', 'xunlei']
        
        for cloud_type in preferred_order:
            if cloud_type in merged_results and displayed_count < max_display:
                items = merged_results[cloud_type]
                if items and isinstance(items, list):
                    displayed_count = self.add_cloud_type_results(
                        lines, cloud_type, items, displayed_count, max_display, keyword
                    )

        lines.append(f"🎯 共显示 {displayed_count} 条结果，总计 {total_results} 条资源")
        lines.append("💡 提示: 结果仅供参考，请遵守相关法律法规")
        lines.append("🔗 复制链接时请确保完整复制")

        return "\n".join(lines)

    def add_cloud_type_results(self, lines, cloud_type, items, displayed_count, max_display, keyword):
        """添加特定云盘类型的搜索结果"""
        type_name = self.get_type_name(cloud_type)
        lines.append(f"📦 {type_name}资源:")

        count_in_type = 0
        max_per_type = 2  # 每个类型最多显示2条以确保完整链接

        for item in items:
            if displayed_count >= max_display or count_in_type >= max_per_type:
                break

            if isinstance(item, dict):
                # 获取完整链接
                full_url = self.get_complete_url(item, cloud_type)
                title = self.generate_title(item, keyword, cloud_type)
                size = str(item.get('size', ''))
                time = str(item.get('time', ''))
                pwd = str(item.get('pwd', item.get('password', '')))
                
                lines.append(f"{displayed_count + 1}. {title}")
                if full_url:
                    lines.append(f"   🔗 {full_url}")
                if size and size not in ['', '未知大小']:
                    lines.append(f"   📦 大小: {size}")
                if time and time not in ['', '未知时间']:
                    lines.append(f"   ⏰ 时间: {time}")
                if pwd and pwd not in ['', '无密码']:
                    lines.append(f"   🔑 密码: {pwd}")
                lines.append("")
                
                displayed_count += 1
                count_in_type += 1

        return displayed_count

    def get_complete_url(self, item: dict, cloud_type: str) -> str:
        """获取完整的URL"""
        url = item.get('url') or item.get('link') or item.get('download_url') or ''
        
        if not url:
            return ""
        
        # 如果URL已经是完整格式，直接返回
        if url.startswith(('http://', 'https://')):
            return url
        
        # 如果URL被截断（包含...），尝试重建完整URL
        if '...' in url:
            # 尝试从原始数据中获取完整URL
            full_url = item.get('full_url') or item.get('complete_url') or ''
            if full_url and full_url.startswith(('http://', 'https://')):
                return full_url
            
            # 尝试修复被截断的URL
            return self.reconstruct_url(url, cloud_type)
        
        # 对于相对路径，添加对应的域名
        if url.startswith('/'):
            base_url = self.cloud_domains.get(cloud_type, 'https://')
            return urljoin(base_url, url)
        
        # 其他情况直接返回
        return url

    def reconstruct_url(self, truncated_url: str, cloud_type: str) -> str:
        """重建被截断的URL"""
        # 移除截断标记
        url = truncated_url.replace('...', '')
        
        # 根据不同网盘模式重建完整URL
        patterns = {
            'baidu': [
                r'(pan\.baidu\.com/s/[a-zA-Z0-9_-]+)',
                r'([a-zA-Z0-9_-]{23})'  # 百度分享码通常是23位
            ],
            'aliyun': [
                r'(alipan\.com/s/[a-zA-Z0-9]+)',
                r'(aliyundrive\.com/s/[a-zA-Z0-9]+)'
            ],
            'quark': [
                r'(pan\.quark\.cn/s/[a-zA-Z0-9]+)'
            ],
            'xunlei': [
                r'(pan\.xunlei\.com/s/[a-zA-Z0-9_-]+)'
            ],
            '115': [
                r'(115\.com/s/[a-zA-Z0-9_-]+)'
            ],
            'uc': [
                r'(drive\.uc\.cn/s/[a-zA-Z0-9]+)'
            ]
        }
        
        if cloud_type in patterns:
            for pattern in patterns[cloud_type]:
                match = re.search(pattern, url)
                if match:
                    found_part = match.group(1)
                    # 添加https协议
                    if not found_part.startswith(('http://', 'https://')):
                        return f"https://{found_part}"
                    return found_part
        
        # 通用处理：尝试提取可能的部分并重建
        if any(domain in url for domain in ['baidu', 'aliyun', 'quark', 'xunlei', '115', 'uc']):
            # 提取域名和路径
            domain_match = re.search(r'([a-zA-Z0-9.-]+\.(?:com|cn|net))/s/([a-zA-Z0-9_-]+)', url)
            if domain_match:
                domain = domain_match.group(1)
                path = domain_match.group(2)
                return f"https://{domain}/s/{path}"
        
        return truncated_url  # 如果无法重建，返回原始（可能不完整）的URL

    def generate_title(self, item: dict, keyword: str, cloud_type: str) -> str:
        """生成资源标题"""
        title = item.get('title') or item.get('name') or item.get('filename') or ''
        
        if not title or title in ['无标题', '未知标题']:
            type_name = self.get_type_name(cloud_type)
            return f"{keyword} {type_name}资源"
        
        # 清理标题
        title = re.sub(r'【.*?】|\[.*?\]|\(.*?\)', '', title)
        title = re.sub(r'\s+', ' ', title).strip()
        
        if len(title) > 30:
            return title[:27] + "..."
        return title

    def get_type_name(self, cloud_type: str) -> str:
        """获取网盘类型的中文名称"""
        type_map = {
            "baidu": "百度网盘", "aliyun": "阿里云盘", "quark": "夸克网盘",
            "tianyi": "天翼云盘", "uc": "UC网盘", "mobile": "移动云盘",
            "115": "115网盘", "xunlei": "迅雷云盘"
        }
        return type_map.get(cloud_type, cloud_type)

    async def terminate(self):
        logger.info("网盘资源搜索插件已卸载")
