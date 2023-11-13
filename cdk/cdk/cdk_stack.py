from aws_cdk import (
    Stack,
    aws_apigateway as apigw,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_dynamodb as ddb,
    aws_iam as iam,
    RemovalPolicy,
    aws_stepfunctions as sfn, aws_stepfunctions_tasks as tasks,
    CfnOutput, Duration
)
import pathlib as path
from constructs import Construct

class ChartAutomationCdkStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # create s3 bucket for storing artifacts
        self.s3_bucket = s3.Bucket(
            self, 
            "S3Bucket",
            removal_policy=RemovalPolicy.DESTROY,
            encryption=s3.BucketEncryption.KMS_MANAGED
        )

        # Create transcribe Lambda function 
        transcribe_lambda = lambda_.Function(
            self, 
            "TranscribeLambda",
             handler="main.lambda_handler",
             runtime=lambda_.Runtime.PYTHON_3_9,
             code=lambda_.Code.from_asset("lambda/transcribe")
        )

        transcribe_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions = [
                    "transcribe:StartMedicalTranscriptionJob",
                    "transcribe:GetMedicalTranscriptionJob"
                ],
                resources =["*"]
            )
        )

        # Add s3 permission to transcribe lambda role policy
        self.s3_bucket.grant_read_write(transcribe_lambda)

        # Create Bedrock Helper Lambda function 
        bedrock_lambda = lambda_.Function(
            self, 
            "BedrockLambda",
             handler="main.lambda_handler",
             runtime=lambda_.Runtime.PYTHON_3_9,
             code=lambda_.Code.from_asset("lambda/bedrock"),
             timeout=Duration.seconds(600)
        )

        bedrock_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions = [
                    'bedrock:*'
                ],
                resources = ["*"]
            )
        )
        # Add s3 permission to bedrock lambda role policy
        self.s3_bucket.grant_read(bedrock_lambda)

        # Create comprehend health Lambda function 
        comprehend_health_lambda = lambda_.Function(
            self, 
            "ComprehendHealthLambda",
             handler="main.lambda_handler",
             runtime=lambda_.Runtime.PYTHON_3_9,
             code=lambda_.Code.from_asset("lambda/comprehend-health"),
             
        )

        comprehend_health_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions = [
                    "comprehendmedical:DetectEntitiesV2"
                ],
                resources = ["*"]
            )
        )

         # Step functions Definition

        submit_transcribe_job = tasks.LambdaInvoke(
            self, "Submit Transcribe Job",
            lambda_function=transcribe_lambda,
            output_path="$.Payload"
        )

        check_transcription_status = tasks.LambdaInvoke(
            self, "Check Transcription Status",
            lambda_function=transcribe_lambda,
            output_path="$.Payload"
        )

        invoke_bedrock_lambda  = tasks.LambdaInvoke(
            self, "Perform Summarization With Bedrock",
            lambda_function=bedrock_lambda,
            output_path="$.Payload"
        )

        invoke_comprehend_health_lambda  = tasks.LambdaInvoke(
            self, "Detect Entities With Comprehend",
            lambda_function=comprehend_health_lambda,
            output_path="$.Payload"
        )

        wait_job = sfn.Wait(
            self, "Wait 30 Seconds",
            time=sfn.WaitTime.duration(
                Duration.seconds(30))
        )

        fail_job = sfn.Fail(
            self, "Fail",
            cause='Conversation analysis Failed'
        )

        succeed_job = sfn.Succeed(
            self, "Succeeded",
            comment='Conversation analysis succeeded'
        )

        bedrock_chain = invoke_bedrock_lambda.next(invoke_comprehend_health_lambda).next(succeed_job)
        chain = submit_transcribe_job.next(wait_job)\
            .next(check_transcription_status)\
            .next(sfn.Choice(self, "Transcription Complete?")\
                .when(sfn.Condition.string_equals("$.Outputs.TranscriptionOutput.TranscriptionJobStatus", "COMPLETED"), bedrock_chain)\
                .when(sfn.Condition.string_equals("$.Outputs.TranscriptionOutput.TranscriptionJobStatus", "FAILED"), fail_job)\
                .otherwise(wait_job))

        state_machine = sfn.StateMachine(
            self, "StateMachine",
            definition_body=sfn.DefinitionBody.from_chainable(chain),
            timeout=Duration.minutes(5)
        )

        # Create API Lambda function 
        api_lambda = lambda_.Function(
            self, 
            "APILambda",
             handler="main.lambda_handler",
             runtime=lambda_.Runtime.PYTHON_3_9,
             code=lambda_.Code.from_asset("lambda/api"),
             environment={
                "STATE_MACHINE_ARN": state_machine.state_machine_arn
            }
        )
        # add step functions permission to api lambda role policy
        state_machine.grant_start_execution(api_lambda)

        # Create API Gateway
        self.api = apigw.LambdaRestApi(
            self, 
            "ChartAutomationAPI",
            handler=api_lambda
        )
        api_endpoint = self.api.root.add_resource("api")
        api_endpoint.add_method("POST")

        CfnOutput(self, "API Endpoint", value=self.api.url)
        CfnOutput(self, "S3 Bucket", value=self.s3_bucket.bucket_name)


    

