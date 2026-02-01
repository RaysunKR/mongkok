import asyncio
import re
from typing import Dict, Any, List, Optional
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
import json
import time
from ..utils.logger import get_logger
from ..utils.config_loader import ConfigLoader
from ..utils.security import SecurityManager


class WebBrowser:
    """网络浏览和信息收集模块"""

    # 常用搜索引擎模板
    SEARCH_ENGINES = {
        'google': 'https://www.google.com/search?q={query}',
        'bing': 'https://www.bing.com/search?q={query}',
        'baidu': 'https://www.baidu.com/s?wd={query}',
        'duckduckgo': 'https://duckduckgo.com/?q={query}'
    }

    def __init__(self, config: ConfigLoader = None):
        self._config = config or ConfigLoader()
        self._logger = get_logger('WebBrowser')
        self._security = SecurityManager(self._config)

        capabilities = self._config.capabilities
        self._enabled = capabilities.get('web_browsing', True)

        self._timeout = self._config.advanced.get('timeout_seconds', 30)
        self._max_retries = self._config.advanced.get('max_retries', 3)

        # 请求头
        self._headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
        }

        # 已访问URL缓存
        self._visited_urls: Dict[str, Dict[str, Any]] = {}
        self._search_cache: Dict[str, List[Dict[str, Any]]] = {}

    async def search(
        self,
        query: str,
        engine: str = 'baidu',
        max_results: int = 10,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """网络搜索"""
        if not self._enabled:
            return {'success': False, 'error': '网络浏览功能未启用'}

        # 安全检查
        allowed, reason = self._security.check_content_safety(query)
        if not allowed:
            return {'success': False, 'error': '内容安全检查失败', 'reason': reason}

        # 检查缓存
        cache_key = f"{engine}:{query}"
        if use_cache and cache_key in self._search_cache:
            self._logger.info(f"使用搜索缓存: {query}")
            return {
                'success': True,
                'results': self._search_cache[cache_key],
                'cached': True
            }

        try:
            # 构建搜索URL
            if engine not in self.SEARCH_ENGINES:
                engine = 'baidu'

            search_url = self.SEARCH_ENGINES[engine].format(
                query=query.replace(' ', '+')
            )
            self._logger.info(f"执行搜索: {query} (引擎: {engine})")

            results = await self._fetch_search_results(
                search_url, max_results, engine
            )

            # 缓存结果
            self._search_cache[cache_key] = results

            self._logger.info(f"搜索完成，找到 {len(results)} 个结果")

            return {
                'success': True,
                'results': results,
                'query': query,
                'engine': engine
            }

        except Exception as e:
            self._logger.error(f"搜索失败: {e}")
            return {
                'success': False,
                'error': '搜索失败',
                'reason': str(e)
            }

    async def _fetch_search_results(
        self,
        url: str,
        max_results: int,
        engine: str
    ) -> List[Dict[str, Any]]:
        """获取搜索结果"""
        results = []

        for attempt in range(self._max_retries):
            try:
                async with aiohttp.ClientSession(
                    headers=self._headers,
                    timeout=aiohttp.ClientTimeout(total=self._timeout)
                ) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            self._logger.warning(f"搜索请求返回状态码: {response.status}")
                            continue

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        # 根据不同搜索引擎解析结果
                        if engine == 'baidu':
                            results = self._parse_baidu_results(soup, max_results)
                        elif engine == 'google':
                            results = self._parse_google_results(soup, max_results)
                        elif engine == 'bing':
                            results = self._parse_bing_results(soup, max_results)
                        else:
                            results = self._parse_generic_results(soup, max_results)

                        if results:
                            break

            except Exception as e:
                self._logger.warning(f"搜索尝试 {attempt + 1} 失败: {e}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))

        return results[:max_results]

    def _parse_baidu_results(self, soup: BeautifulSoup, max_results: int) -> List[Dict[str, Any]]:
        """解析百度搜索结果"""
        results = []
        items = soup.select('.result')

        for item in items[:max_results]:
            try:
                title_elem = item.select_one('.t a') or item.select_one('h3 a')
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')

                description_elem = item.select_one('.c-abstract') or item.select_one('.c-span-last')
                description = description_elem.get_text(strip=True) if description_elem else ''

                results.append({
                    'title': title,
                    'url': link,
                    'description': description,
                    'source': 'baidu'
                })
            except Exception as e:
                self._logger.debug(f"解析百度结果失败: {e}")
                continue

        return results

    def _parse_google_results(self, soup: BeautifulSoup, max_results: int) -> List[Dict[str, Any]]:
        """解析Google搜索结果"""
        results = []
        items = soup.select('div.g')

        for item in items[:max_results]:
            try:
                title_elem = item.select_one('h3')
                link_elem = item.select_one('a')
                description_elem = item.select_one('.VwiC3b')

                if not title_elem or not link_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = link_elem.get('href', '')
                description = description_elem.get_text(strip=True) if description_elem else ''

                results.append({
                    'title': title,
                    'url': link,
                    'description': description,
                    'source': 'google'
                })
            except Exception as e:
                self._logger.debug(f"解析Google结果失败: {e}")
                continue

        return results

    def _parse_bing_results(self, soup: BeautifulSoup, max_results: int) -> List[Dict[str, Any]]:
        """解析Bing搜索结果"""
        results = []
        items = soup.select('.b_algo')

        for item in items[:max_results]:
            try:
                title_elem = item.select_one('h2 a')
                description_elem = item.select_one('.b_caption p')

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '')
                description = description_elem.get_text(strip=True) if description_elem else ''

                results.append({
                    'title': title,
                    'url': link,
                    'description': description,
                    'source': 'bing'
                })
            except Exception as e:
                self._logger.debug(f"解析Bing结果失败: {e}")
                continue

        return results

    def _parse_generic_results(self, soup: BeautifulSoup, max_results: int) -> List[Dict[str, Any]]:
        """通用搜索结果解析"""
        results = []
        # 尝试查找链接
        links = soup.find_all('a', href=True)

        for link in links[:max_results * 2]:  # 多获取一些，然后筛选
            href = link.get('href', '')
            if (href.startswith('http') and
                not any(excluded in href for excluded in ['google.com', 'bing.com', 'baidu.com'])):
                text = link.get_text(strip=True)
                if text and len(text) > 3:
                    results.append({
                        'title': text,
                        'url': href,
                        'description': '',
                        'source': 'generic'
                    })
                    if len(results) >= max_results:
                        break

        return results

    async def fetch_page(
        self,
        url: str,
        extract_text: bool = True,
        extract_links: bool = False,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """获取网页内容"""
        if not self._enabled:
            return {'success': False, 'error': '网络浏览功能未启用'}

        # 安全检查URL
        if not self._is_safe_url(url):
            return {'success': False, 'error': 'URL不安全或格式无效'}

        # 检查缓存
        if use_cache and url in self._visited_urls:
            self._logger.info(f"使用缓存: {url}")
            return {
                'success': True,
                'url': url,
                **self._visited_urls[url],
                'cached': True
            }

        try:
            self._logger.info(f"获取页面: {url}")

            async with aiohttp.ClientSession(
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=self._timeout)
            ) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return {
                            'success': False,
                            'error': f'HTTP错误: {response.status}',
                            'url': url
                        }

                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    data = {
                        'url': url,
                        'status': response.status,
                        'content_length': len(html),
                    }

                    # 提取文本
                    if extract_text:
                        # 移除脚本和样式
                        for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                            script.decompose()

                        text = soup.get_text(separator='\n', strip=True)
                        text = re.sub(r'\n\s*\n', '\n\n', text)  # 合并多余空行
                        data['text'] = text

                    # 提取链接
                    if extract_links:
                        links = []
                        for link in soup.find_all('a', href=True):
                            href = link.get('href', '')
                            full_url = urljoin(url, href)
                            if self._is_safe_url(full_url):
                                links.append({
                                    'text': link.get_text(strip=True),
                                    'url': full_url
                                })
                        data['links'] = links

                    # 缓存结果
                    self._visited_urls[url] = data

                    return {'success': True, **data}

        except asyncio.TimeoutError:
            return {'success': False, 'error': '请求超时', 'url': url}
        except Exception as e:
            self._logger.error(f"获取页面失败: {e}")
            return {'success': False, 'error': str(e), 'url': url}

    def _is_safe_url(self, url: str) -> bool:
        """检查URL是否安全"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False

            if parsed.scheme not in ['http', 'https']:
                return False

            # 检查是否是内网地址
            if parsed.hostname in ['localhost', '127.0.0.1', '0.0.0.0', '::1']:
                return False

            # 检查内网IP范围
            if parsed.hostname:
                import ipaddress
                try:
                    ip = ipaddress.ip_address(parsed.hostname)
                    if ip.is_private or ip.is_loopback or ip.is_link_local:
                        return False
                except ValueError:
                    pass

            return True

        except Exception:
            return False

    async def collect_information(
        self,
        query: str,
        max_pages: int = 5,
        max_depth: int = 1
    ) -> Dict[str, Any]:
        """收集和整理信息"""
        if not self._enabled:
            return {'success': False, 'error': '网络浏览功能未启用'}

        try:
            self._logger.info(f"开始信息收集: {query}")

            # 第一步：搜索
            search_result = await self.search(query, max_results=max_pages)
            if not search_result.get('success'):
                return search_result

            search_results = search_result['results']
            collected_info = []

            # 第二步：访问搜索结果页面
            for result in search_results[:max_pages]:
                url = result.get('url', '')
                if not url:
                    continue

                page_result = await self.fetch_page(url, extract_text=True)

                if page_result.get('success'):
                    collected_info.append({
                        'source_title': result.get('title', ''),
                        'source_url': url,
                        'source_description': result.get('description', ''),
                        'content': page_result.get('text', ''),
                        'content_length': page_result.get('content_length', 0)
                    })

                # 短暂延迟避免请求过快
                await asyncio.sleep(0.5)

            # 第三步：整理信息
            summary = self._summarize_collected_info(collected_info, query)

            self._logger.info(f"信息收集完成，收集了 {len(collected_info)} 个页面的信息")

            return {
                'success': True,
                'query': query,
                'summary': summary,
                'sources': [info['source_url'] for info in collected_info],
                'detailed_info': collected_info,
                'collection_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            self._logger.error(f"信息收集失败: {e}")
            return {
                'success': False,
                'error': '信息收集失败',
                'reason': str(e)
            }

    def _summarize_collected_info(
        self,
        info_list: List[Dict[str, Any]],
        query: str
    ) -> str:
        """汇总收集的信息"""
        if not info_list:
            return f"未找到关于 '{query}' 的相关信息。"

        summary_parts = [
            f"## 信息收集摘要",
            f"**查询**: {query}",
            f"**来源数量**: {len(info_list)}",
            "",
            "### 主要信息来源:"
        ]

        for i, info in enumerate(info_list, 1):
            title = info.get('source_title', '无标题')
            url = info.get('source_url', '')
            desc = info.get('source_description', '')[:200]

            summary_parts.append(f"{i}. **{title}**")
            summary_parts.append(f"   - URL: {url}")
            summary_parts.append(f"   - 描述: {desc}")
            if len(desc) >= 200:
                summary_parts[-1] += "..."

        # 内容长度统计
        total_length = sum(info.get('content_length', 0) for info in info_list)
        summary_parts.extend([
            "",
            f"### 统计信息",
            f"- 总内容长度: {total_length:,} 字符"
        ])

        return "\n".join(summary_parts)

    async def search_and_research(
        self,
        query: str,
        num_iterations: int = 2
    ) -> Dict[str, Any]:
        """递进式搜索 - 根据初搜索结果进行更深入的搜索"""
        if not self._enabled:
            return {'success': False, 'error': '网络浏览功能未启用'}

        all_results = []
        current_query = query

        for i in range(num_iterations):
            self._logger.info(f"递进搜索第 {i + 1} 轮: {current_query}")

            result = await self.collect_information(current_query, max_pages=3)

            if not result.get('success'):
                break

            all_results.append(result)

            # 如果不是最后一轮，可以选择根据结果优化查询
            if i < num_iterations - 1:
                # 这里可以添加逻辑来优化查询
                current_query = query  # 简化处理，保持原查询

            await asyncio.sleep(1)

        return {
            'success': True,
            'original_query': query,
            'iterations': len(all_results),
            'results': all_results,
            'total_sources': sum(len(r.get('detailed_info', [])) for r in all_results)
        }
