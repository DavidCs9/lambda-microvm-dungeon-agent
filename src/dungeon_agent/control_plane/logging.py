"""Shared Powertools Logger for control-plane Lambdas."""

from aws_lambda_powertools import Logger

logger = Logger(service="dungeon-agent-control-plane")
