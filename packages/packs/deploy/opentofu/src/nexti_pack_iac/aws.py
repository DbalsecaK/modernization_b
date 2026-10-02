# ruff: noqa: E501 - the HCL templates keep the lines OpenTofu formats
"""The AWS IaC of a target (spec 8.4, ADR-0021), deterministic: a VPC with private subnets, the service on ECS Fargate
behind an Application Load Balancer, the database on RDS (PostgreSQL, Oracle, SQL Server or MySQL) or, for MongoDB
(ADR-0029), on Amazon DocumentDB, encrypted and private, its password generated and kept in Secrets Manager, and the
logs in CloudWatch. Everything is tagged."""

from nexti_pack_iac.common import Target

ENGINES = {
    "postgresql": ("postgres", "16", 5432, ""),
    "oracle": ("oracle-se2", "19", 1521, '  license_model             = "license-included"\n'),
    "sqlserver": ("sqlserver-ex", "16.00", 1433, '  license_model             = "license-included"\n'),
    "mysql": ("mysql", "8.4", 3306, ""),
}
DOCUMENTDB_PORT = 27017
RDS_ENDPOINT = "aws_db_instance.main.address"
DOCUMENTDB_ENDPOINT = "aws_docdb_cluster.main.endpoint"

RDS = """resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier                = "${local.name}-db"
  engine                    = "__ENGINE__"
  engine_version            = "__VERSION__"
  instance_class            = var.db_instance_class
  allocated_storage         = 20
  storage_encrypted         = true
  publicly_accessible       = false
  deletion_protection       = true
  backup_retention_period   = 7
  db_subnet_group_name      = aws_db_subnet_group.main.name
  vpc_security_group_ids    = [aws_security_group.db.id]
  username                  = "app"
  password                  = random_password.db.result
  final_snapshot_identifier = "${local.name}-final"
__LICENSE__}
"""

# MongoDB (ADR-0029): an Amazon DocumentDB cluster (MongoDB-compatible) in the private subnets, encrypted, TLS required
# by its parameter group, its audit and profiler logs exported to CloudWatch with retention.
DOCUMENTDB = """resource "aws_docdb_subnet_group" "main" {
  name       = "${local.name}-docdb"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_docdb_cluster_parameter_group" "main" {
  name   = "${local.name}-docdb"
  family = "docdb5.0"
  parameter {
    name  = "tls"
    value = "enabled"
  }
  parameter {
    name  = "audit_logs"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "docdb" {
  for_each          = toset(["audit", "profiler"])
  name              = "/aws/docdb/${local.name}-db/${each.key}"
  retention_in_days = 30
}

resource "aws_docdb_cluster" "main" {
  cluster_identifier              = "${local.name}-db"
  engine                          = "docdb"
  engine_version                  = "5.0.0"
  master_username                 = "app"
  master_password                 = random_password.db.result
  storage_encrypted               = true
  deletion_protection             = true
  backup_retention_period         = 7
  db_subnet_group_name            = aws_docdb_subnet_group.main.name
  db_cluster_parameter_group_name = aws_docdb_cluster_parameter_group.main.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  enabled_cloudwatch_logs_exports = ["audit", "profiler"]
  final_snapshot_identifier       = "${local.name}-final"
  depends_on                      = [aws_cloudwatch_log_group.docdb]
}

resource "aws_docdb_cluster_instance" "main" {
  count              = 2
  identifier         = "${local.name}-db-${count.index}"
  cluster_identifier = aws_docdb_cluster.main.id
  instance_class     = var.db_instance_class
}
"""


def _database(target: Target) -> tuple[str, int, str]:
    """The database resources, their port and the expression of their endpoint."""
    if target.database == "mongodb":
        return DOCUMENTDB, DOCUMENTDB_PORT, DOCUMENTDB_ENDPOINT
    engine, version, port, license_model = ENGINES.get(target.database, ENGINES["postgresql"])
    rds = RDS.replace("__ENGINE__", engine).replace("__VERSION__", version).replace("__LICENSE__", license_model)
    return rds, port, RDS_ENDPOINT


# The service on ECS Fargate behind an Application Load Balancer.
CONTAINER_SECURITY_GROUPS = """resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  name   = "${local.name}-app"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

"""

CONTAINER_SERVICE = """# -- service: the generated application in a container, behind the load balancer -----------------------------------
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_iam_role" "execution" {
  name = "${local.name}-execution"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  name = "${local.name}-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.db.arn] }]
  })
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name         = local.name
    image        = var.container_image
    essential    = true
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    environment  = [{ name = "DB_HOST", value = aws_db_instance.main.address }]
    secrets      = [{ name = "DB_CREDENTIALS", valueFrom = aws_secretsmanager_secret.db.arn }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "app"
      }
    }
  }])
}

resource "aws_lb" "main" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "app" {
  name        = local.name
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path = "/actuator/health"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_ecs_service" "app" {
  name            = local.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = local.name
    container_port   = 8080
  }
}
"""

# Serverless (ADR-0027): the same image as a Lambda function in the private subnets, behind an API Gateway HTTP API.
SERVERLESS_SECURITY_GROUPS = """resource "aws_security_group" "app" {
  name   = "${local.name}-app"
  vpc_id = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

"""

SERVERLESS_SERVICE = """# -- service: the generated application as a Lambda function in the private subnets, behind an HTTP API -----------
resource "aws_cloudwatch_log_group" "app" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "secrets" {
  name = "${local.name}-secrets"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.db.arn] }]
  })
}

resource "aws_lambda_function" "app" {
  function_name = local.name
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = var.container_image
  memory_size   = 2048
  timeout       = 30
  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.app.id]
  }
  environment {
    variables = {
      DB_HOST           = aws_db_instance.main.address
      DB_CREDENTIALS_ID = aws_secretsmanager_secret.db.arn
    }
  }
  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.app.name
  }
  tracing_config {
    mode = "Active"
  }
  depends_on = [aws_iam_role_policy_attachment.lambda_vpc, aws_iam_role_policy.secrets]
}

resource "aws_apigatewayv2_api" "main" {
  name          = local.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "app" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "app" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.app.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format          = jsonencode({ requestId = "$context.requestId", routeKey = "$context.routeKey", status = "$context.status" })
  }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
"""


def files(target: Target) -> dict[str, str]:
    database, port, endpoint = _database(target)
    name = target.name
    security_groups = SERVERLESS_SECURITY_GROUPS if target.serverless else CONTAINER_SECURITY_GROUPS
    service = (SERVERLESS_SERVICE if target.serverless else CONTAINER_SERVICE).replace(RDS_ENDPOINT, endpoint)
    main = f'''terraform {{
  required_version = ">= 1.8"
  required_providers {{
    aws    = {{ source = "hashicorp/aws", version = "~> 6.0" }}
    random = {{ source = "hashicorp/random", version = "~> 3.6" }}
  }}
}}

provider "aws" {{
  region = var.region
  default_tags {{
    tags = local.tags
  }}
}}

locals {{
  name = "{name}"
  tags = {{
    project     = "{name}"
    environment = var.environment
    managed-by  = "nexti"
  }}
}}

data "aws_availability_zones" "available" {{
  state = "available"
}}

# -- network: private subnets for the service and the database, public subnets only for the load balancer --------
resource "aws_vpc" "main" {{
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}}

resource "aws_subnet" "public" {{
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
}}

resource "aws_subnet" "private" {{
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]
}}

resource "aws_internet_gateway" "main" {{
  vpc_id = aws_vpc.main.id
}}

resource "aws_eip" "nat" {{
  domain = "vpc"
}}

resource "aws_nat_gateway" "main" {{
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
}}

resource "aws_route_table" "public" {{
  vpc_id = aws_vpc.main.id
  route {{
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }}
}}

resource "aws_route_table" "private" {{
  vpc_id = aws_vpc.main.id
  route {{
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }}
}}

resource "aws_route_table_association" "public" {{
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}}

resource "aws_route_table_association" "private" {{
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}}

{security_groups}resource "aws_security_group" "db" {{
  name   = "${{local.name}}-db"
  vpc_id = aws_vpc.main.id
  ingress {{
    from_port       = {port}
    to_port         = {port}
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }}
}}

# -- database: the tables of the legacy, on a managed engine, encrypted and private --------------------------------
resource "random_password" "db" {{
  length  = 32
  special = false
}}

resource "aws_secretsmanager_secret" "db" {{
  name                    = "${{local.name}}/db"
  recovery_window_in_days = 7
}}

resource "aws_secretsmanager_secret_version" "db" {{
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({{ username = "app", password = random_password.db.result }})
}}

{database}
{service}'''
    variables = """variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "container_image" {
  type        = string
  description = "The image of the generated service, built and pushed by the pipeline of the customer"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
"""
    if not target.serverless:
        variables += """
variable "certificate_arn" {
  type        = string
  description = "The ACM certificate of the service's domain (TLS at the load balancer)"
}
"""
    url = "aws_apigatewayv2_api.main.api_endpoint" if target.serverless else '"https://${aws_lb.main.dns_name}"'
    outputs = f"""output "url" {{
  value = {url}
}}

output "database_endpoint" {{
  value = {endpoint}
}}
"""
    return {"main.tf": main, "variables.tf": variables, "outputs.tf": outputs}
