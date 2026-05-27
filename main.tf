# infra/main.tf

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Configura o provedor da nuvem (AWS) e a região padrão de deploy
provider "aws" {
  region = "us-east-1"
}

# 1. Provedor da Fila de Trabalho (Map)
resource "aws_sqs_queue" "fila_trabalho" {
  name                       = "fila-trabalho"
  visibility_timeout_seconds = 60
}

# 2. Provedor da Fila de Resultados (Reduce)
resource "aws_sqs_queue" "fila_resultado" {
  name                       = "fila-resultado"
  visibility_timeout_seconds = 60
}

# 3. Provedor da Fila de Eventos (Telemetria/Métricas)
resource "aws_sqs_queue" "fila_eventos" {
  name                       = "fila-eventos"
  visibility_timeout_seconds = 10
}