"""Slack reader."""
import logging
import os
import time
from datetime import datetime
from typing import List, Optional

from llama_index.readers.base import BaseReader
from llama_index.readers.schema.base import Document

logger = logging.getLogger(__name__)


class SlackReader(BaseReader):
    """Slack reader.

    Reads conversations from channels. If an earliest_date is provided, an
    optional latest_date can also be provided. If no latest_date is provided,
    we assume the latest date is the current timestamp.

    Args:
        slack_token (Optional[str]): Slack token. If not provided, we
            assume the environment variable `SLACK_BOT_TOKEN` is set.
        earliest_date (Optional[datetime]): Earliest date from which
            to read conversations. If not provided, we read all messages.
        latest_date (Optional[datetime]): Latest date from which to
            read conversations. If not provided, defaults to current timestamp
            in combination with earliest_date.
    """

    def __init__(
        self,
        slack_token: Optional[str] = None,
        earliest_date: Optional[datetime] = None,
        latest_date: Optional[datetime] = None,
        message_separator: str = "\n\n",
    ) -> None:
        """Initialize with parameters."""
        from slack_sdk import WebClient

        if slack_token is None:
            slack_token = os.environ["SLACK_BOT_TOKEN"]
        if slack_token is None:
            raise ValueError(
                "Must specify `slack_token` or set environment "
                "variable `SLACK_BOT_TOKEN`."
            )
        self.client = WebClient(token=slack_token)
        if latest_date is not None and earliest_date is None:
            raise ValueError(
                "Must specify `earliest_date` if `latest_date` is specified."
            )
        if earliest_date is not None:
            self.earliest_date_timestamp = earliest_date.timestamp()
            if latest_date is not None:
                self.latest_date_timestamp = latest_date.timestamp()
            else:
                self.latest_date_timestamp = datetime.now().timestamp()
        else:
            self.earliest_date_timestamp = None
        res = self.client.api_test()
        if not res["ok"]:
            raise ValueError(f"Error initializing Slack API: {res['error']}")
        
        self.message_separator = message_separator

    def _read_message(self, channel_id: str, message_ts: str) -> str:
        from slack_sdk.errors import SlackApiError

        """Read a message."""

        messages_text: List[str] = []
        next_cursor = None
        while True:
            try:
                # https://slack.com/api/conversations.replies
                # List all replies to a message, including the message itself.
                if self.earliest_date_timestamp is None:
                    result = self.client.conversations_replies(
                        channel=channel_id, ts=message_ts, cursor=next_cursor
                    )
                else:
                    result = self.client.conversations_replies(
                        channel=channel_id,
                        ts=message_ts,
                        cursor=next_cursor,
                        oldest=str(self.earliest_date_timestamp),
                        latest=str(self.latest_date_timestamp),
                    )
                messages = result["messages"]
                messages_text.extend(message["text"] for message in messages)
                if not result["has_more"]:
                    break

                next_cursor = result["response_metadata"]["next_cursor"]
            except SlackApiError as e:
                if e.response["error"] == "ratelimited":
                    logger.error(
                        "Rate limit error reached, sleeping for: {} seconds".format(
                            e.response.headers["retry-after"]
                        )
                    )
                    time.sleep(int(e.response.headers["retry-after"]))
                else:
                    logger.error("Error parsing conversation replies: {}".format(e))

        return self.message_separator.join(messages_text)

    def _read_channel(self, channel_id: str, reverse_chronological: bool) -> str:
        from slack_sdk.errors import SlackApiError

        """Read a channel."""

        result_messages: List[str] = []
        next_cursor = None
        while True:
            try:
                # Call the conversations.history method using the WebClient
                # conversations.history returns the first 100 messages by default
                # These results are paginated,
                # see: https://api.slack.com/methods/conversations.history$pagination
                if self.earliest_date_timestamp is None:
                    result = self.client.conversations_history(
                        channel=channel_id,
                        cursor=next_cursor,
                    )
                else:
                    result = self.client.conversations_history(
                        channel=channel_id,
                        cursor=next_cursor,
                        oldest=str(self.earliest_date_timestamp),
                        latest=str(self.latest_date_timestamp),
                    )                    
                conversation_history = result["messages"]
                # Print results
                logger.info(
                    "{} messages found in {}".format(len(conversation_history), id)
                )
                result_messages.extend(
                    self._read_message(channel_id, message["ts"])
                    for message in conversation_history
                )
                if not result["has_more"]:
                    break
                next_cursor = result["response_metadata"]["next_cursor"]

            except SlackApiError as e:
                if e.response["error"] == "ratelimited":
                    logger.error(
                        "Rate limit error reached, sleeping for: {} seconds".format(
                            e.response.headers["retry-after"]
                        )
                    )
                    time.sleep(int(e.response.headers["retry-after"]))
                else:
                    logger.error("Error parsing conversation replies: {}".format(e))

        return (
            self.message_separator.join(result_messages)
            if reverse_chronological
            else self.message_separator.join(result_messages[::-1])
        )

    def load_data(
        self, channel_ids: List[str], reverse_chronological: bool = True
    ) -> List[Document]:
        """Load data from the input directory.

        Args:
            channel_ids (List[str]): List of channel ids to read.
        Returns:
            List[Document]: List of documents.
        """
        results = []
        for channel_id in channel_ids:
            channel_content = self._read_channel(
                channel_id, reverse_chronological=reverse_chronological
            )
            results.append(
                Document(channel_content, extra_info={"channel": channel_id})
            )
        return results


if __name__ == "__main__":
    reader = SlackReader()
    logging.info(reader.load_data(channel_ids=["C04DC2VUY3F"]))
