#!/usr/bin/env python3
"""
测试从文件加载MCAP并上传到云端的脚本
"""

import os
import argparse
import uuid
import json
import logging
from pathlib import Path
from mcap.reader import make_reader
from mcap_data_loader.schemas.airbot_fbs.FloatArray import FloatArray


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_mcap_file(mcap_file: str) -> dict:
    """加载 MCAP 格式数据（参考 mmk_replay.py）"""
    data = {"data": {}, "metadata": {}, "attachments": {}}

    with open(mcap_file, "rb") as f:
        reader = make_reader(f)

        # 读取元数据
        for metadata in reader.iter_metadata():
            try:
                # 修复API差异，使用正确的属性名
                metadata_data = getattr(
                    metadata, "data", getattr(metadata, "metadata", b"")
                )
                metadata_value = json.loads(metadata_data.decode("utf-8"))
                data["metadata"][metadata.name] = metadata_value
                logger.info(f"读取元数据: {metadata.name}")
            except Exception:
                try:
                    metadata_data = getattr(
                        metadata, "data", getattr(metadata, "metadata", b"")
                    )
                    data["metadata"][metadata.name] = metadata_data.decode(
                        "utf-8", errors="ignore"
                    )
                except Exception:
                    data["metadata"][metadata.name] = str(metadata)
                    logger.warning(f"无法解析元数据: {metadata.name}")

        # 读取附件
        for attachment in reader.iter_attachments():
            attachment_data = getattr(attachment, "data", b"")
            data["attachments"][attachment.name] = {
                "media_type": getattr(attachment, "media_type", "unknown"),
                "data_size": len(attachment_data),
            }
            logger.info(
                f"读取附件: {attachment.name} ({getattr(attachment, 'media_type', 'unknown')})"
            )

        # 收集所有消息
        messages_by_topic = {}
        for schema, channel, message in reader.iter_messages():
            topic = channel.topic

            if topic not in messages_by_topic:
                messages_by_topic[topic] = []

            # 解析 FlatBuffers 消息
            if schema.name == "airbot_fbs.FloatArray":
                try:
                    # 使用正确的 FlatBuffers 解析方法
                    float_array = FloatArray.GetRootAs(message.data, 0)

                    # 提取数值
                    values = []
                    for i in range(float_array.ValuesLength()):
                        values.append(float_array.Values(i))

                    # 转换时间戳（纳秒转毫秒）
                    timestamp_ms = message.log_time / 1e6

                    messages_by_topic[topic].append({"t": timestamp_ms, "data": values})
                except Exception as e:
                    logger.warning(f"解析 FlatBuffers 消息失败 (话题: {topic}): {e}")
                    continue

        # 按话题组织数据，按时间戳排序
        for topic, messages in messages_by_topic.items():
            messages.sort(key=lambda x: x["t"])
            data["data"][topic] = messages

    logger.info(f"已加载 MCAP 数据文件: {mcap_file}")
    logger.info(f"包含话题: {list(data['data'].keys())}")
    logger.info(f"元数据项: {list(data['metadata'].keys())}")
    logger.info(f"附件: {list(data['attachments'].keys())}")

    return data


def upload_mcap_to_cloud(
    file_path: str,
    project_id: int,
    endpoint: str = "192.168.215.80",
    username: str = "admin",
    password: str = "123456",
) -> bool:
    """上传MCAP文件到云端"""
    try:
        from dataloop import DataLoopClient

        # 初始化 DataLoop 客户端
        dataloop = DataLoopClient(
            endpoint=endpoint, username=username, password=password
        )

        # 生成唯一的样本ID
        uid = str(uuid.uuid4())

        # 获取文件信息
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)

        logger.info("开始上传文件到云端:")
        logger.info(f"  文件路径: {file_path}")
        logger.info(f"  文件名: {file_name}")
        logger.info(f"  文件大小: {file_size} bytes")
        logger.info(f"  项目ID: {project_id}")
        logger.info(f"  样本ID: {uid}")

        # 上传文件
        message = dataloop.samples.upload_sample(
            project_id=project_id,
            sample_id=uid,
            sample_type="Sequential",
            file_path=file_path,
        )

        logger.info("文件上传成功!")
        logger.info(f"服务器响应: {message}")
        return True

    except ImportError:
        logger.error("dataloop 模块未安装，无法上传到云端")
        logger.error("请运行: pip install dataloop")
        return False
    except Exception as e:
        logger.error(f"上传到云端失败: {str(e)}")
        return False


def analyze_mcap_content(data: dict):
    """分析MCAP文件内容"""
    logger.info("=" * 50)
    logger.info("MCAP 文件内容分析:")
    logger.info("=" * 50)

    # 分析元数据
    if data["metadata"]:
        logger.info("元数据:")
        for key, value in data["metadata"].items():
            if isinstance(value, dict):
                logger.info(
                    f"  {key}: {json.dumps(value, indent=2, ensure_ascii=False)}"
                )
            else:
                logger.info(f"  {key}: {value}")

    # 分析数据话题
    if data["data"]:
        logger.info("\n数据话题:")
        for topic, messages in data["data"].items():
            logger.info(f"  {topic}: {len(messages)} 条消息")
            if messages:
                first_msg = messages[0]
                last_msg = messages[-1]
                logger.info(
                    f"    时间范围: {first_msg['t']:.2f} - {last_msg['t']:.2f} ms"
                )
                if "data" in first_msg:
                    logger.info(f"    数据维度: {len(first_msg['data'])}")

    # 分析附件
    if data["attachments"]:
        logger.info("\n附件:")
        for name, info in data["attachments"].items():
            logger.info(f"  {name}: {info['media_type']}, {info['data_size']} bytes")


def main():
    parser = argparse.ArgumentParser(description="MCAP文件云端上传测试工具")
    parser.add_argument("mcap_file", help="MCAP文件路径")
    parser.add_argument("--project-id", type=int, default=120, help="DataLoop项目ID")
    parser.add_argument(
        "--endpoint", default="192.168.215.80", help="DataLoop服务器地址"
    )
    parser.add_argument("--username", default="admin", help="用户名")
    parser.add_argument("--password", default="123456", help="密码")
    parser.add_argument(
        "--analyze-only", action="store_true", help="仅分析文件内容，不上传"
    )

    args = parser.parse_args()

    try:
        # 检查文件是否存在
        mcap_path = Path(args.mcap_file)
        if not mcap_path.exists():
            logger.error(f"文件不存在: {mcap_path}")
            return 1

        if mcap_path.suffix.lower() != ".mcap":
            logger.error(f"不是MCAP文件: {mcap_path}")
            return 1

        # 加载MCAP文件
        logger.info(f"正在加载MCAP文件: {mcap_path}")
        data = load_mcap_file(str(mcap_path))

        # 分析文件内容
        analyze_mcap_content(data)

        if args.analyze_only:
            logger.info("仅分析模式，跳过上传")
            return 0

        # 上传到云端
        logger.info("\n" + "=" * 50)
        logger.info("开始上传到云端")
        logger.info("=" * 50)

        success = upload_mcap_to_cloud(
            file_path=str(mcap_path),
            project_id=args.project_id,
            endpoint=args.endpoint,
            username=args.username,
            password=args.password,
        )

        if success:
            logger.info("测试成功!")
            return 0
        else:
            logger.error("测试失败!")
            return 1

    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
