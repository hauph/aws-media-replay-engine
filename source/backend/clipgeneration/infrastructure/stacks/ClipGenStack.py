import os
import sys
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_ssm as ssm,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks
)
from cdk_nag import NagSuppressions


# Ask Python interpreter to search for modules in the topmost folder. This is required to access the shared.infrastructure.helpers module
sys.path.append('../../../')

from shared.infrastructure.helpers import common

RUNTIME_SOURCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), os.pardir, 'runtime')


MRE_EVENT_BUS = "aws-mre-event-bus"

class ClipGenStack(Stack):

    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Get the MediaConvert Regional endpoint
        self.media_convert_endpoint = common.MreCdkCommon.get_media_convert_endpoint(self)

        # Get the Existing MRE EventBus as IEventBus
        self.event_bus = common.MreCdkCommon.get_event_bus(self)

        # Get MediaConvert Bucket Name from SSM
        self.media_convert_output_bucket_name = common.MreCdkCommon.get_media_convert_output_bucket_name(self)

        self.event_media_convert_role_arn = common.MreCdkCommon.get_media_convert_role_arn()

        # Get Layers
        self.mre_workflow_helper_layer = common.MreCdkCommon.get_mre_workflow_helper_layer_from_arn(self)
        self.mre_plugin_helper_layer = common.MreCdkCommon.get_mre_plugin_helper_layer_from_arn(self)
        self.timecode_layer = common.MreCdkCommon.get_timecode_layer_from_arn(self)


        # Configure all Lambdas and Step Functions for Clip Gen
        self.configure_clip_gen_lambda()

    def configure_clip_gen_lambda(self):

        
        self.event_clip_gen_lambda_role = iam.Role(
            self,
            "MREEventClipGenIamRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[
                    f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:*"
                ]
            )
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "mediaconvert:DescribeEndpoints",
                    "mediaconvert:GetJob",
                    "mediaconvert:GetQueue",
                    "mediaconvert:CreatePreset",
                    "mediaconvert:GetJobTemplate",
                    "mediaconvert:CreatePreset",
                    "mediaconvert:CreateQueue",
                    "mediaconvert:CreateJobTemplate",
                    "mediaconvert:CreateJob"
                ],
                resources=[
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:jobTemplates/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:presets/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:queues/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:jobs/*"
                        ]
            )
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "events:DescribeEventBus",
                    "events:PutEvents"
                ],
                resources=[
                    f"arn:aws:events:{Stack.of(self).region}:{Stack.of(self).account}:event-bus/{MRE_EVENT_BUS}"
                ]
            )
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "execute-api:Invoke",
                    "execute-api:ManageConnections"
                ],
                resources=[f"arn:aws:execute-api:{Stack.of(self).region}:{Stack.of(self).account}:*"]
            )
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:GetParameter",
                    "ssm:GetParameters",
                    "ssm:GetParametersByPath"
                ],
                resources=[f"arn:aws:ssm:{Stack.of(self).region}:{Stack.of(self).account}:parameter/MRE*"]
            )
        )

        self.event_clip_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:PassRole"
                ],
                resources=[
                    self.event_media_convert_role_arn
                ]
            )
        )
        
        # Function: ClipGen
        self.event_clip_generator_lambda = _lambda.Function(
            self,
            "Mre-ClipGenEventClipGenerator",
            description="Generates Clips for MRE events",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(f"{RUNTIME_SOURCE_DIR}/lambda/EventClipGenerator"),
            handler="mre-event-clip-generator.GenerateClips",
            role=self.event_clip_gen_lambda_role,
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "MediaConvertRole": self.event_media_convert_role_arn,
                #"OutputBucket": "" if not isinstance(self.media_convert_output_bucket_name, str) else self.media_convert_output_bucket_name,
                "OutputBucket": self.media_convert_output_bucket_name,
                "MediaConvertMaxInputJobs": "150",
                "EB_EVENT_BUS_NAME": MRE_EVENT_BUS,
                "MEDIA_CONVERT_ENDPOINT": self.media_convert_endpoint
            },
            layers=[self.mre_workflow_helper_layer,
                     self.mre_plugin_helper_layer
                     ]
        )

        ## END: event-clip-generator LAMBDA ###

        ### START: EventHlsGenerator LAMBDA ###

        self.event_hls_gen_lambda_role = iam.Role(
            self,
            "MREEventHlsGeneratorIamRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        self.event_hls_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[
                    f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:*"
                ]
            )
        )

        self.event_hls_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "mediaconvert:DescribeEndpoints",
                    "mediaconvert:GetJob",
                    "mediaconvert:GetQueue",
                    "mediaconvert:CreatePreset",
                    "mediaconvert:GetJobTemplate",
                    "mediaconvert:CreatePreset",
                    "mediaconvert:CreateQueue",
                    "mediaconvert:CreateJobTemplate",
                    "mediaconvert:CreateJob"
                ],
                resources=[
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:jobTemplates/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:presets/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:queues/*",
                            f"arn:aws:mediaconvert:{Stack.of(self).region}:{Stack.of(self).account}:jobs/*"
                        ]
            )
        )

        self.event_hls_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject"
                ],
                resources=[f"arn:aws:s3:::{self.media_convert_output_bucket_name}/*"]
            )
        )

        self.event_hls_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "execute-api:Invoke",
                    "execute-api:ManageConnections"
                ],
                resources=[f"arn:aws:execute-api:{Stack.of(self).region}:{Stack.of(self).account}:*"]
            )
        )

        self.event_hls_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:DescribeParameters",
                    "ssm:GetParameter",
                    "ssm:GetParameters"
                ],
                resources=[f"arn:aws:ssm:{Stack.of(self).region}:{Stack.of(self).account}:parameter/MRE*"]
            )
        )

        self.event_hls_create_manifest_lambda = _lambda.Function(
            self,
            "Mre-ClipGenEventHlsGenerator",
            description="Generates Hls Manifest for MRE events",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(f"{RUNTIME_SOURCE_DIR}/lambda/EventHlsManifestGenerator"),
            handler="event_hls_manifest_gen.create_hls_manifest",
            role=self.event_hls_gen_lambda_role,
            memory_size=512,
            timeout=Duration.minutes(15),
            environment={
                "MediaConvertRole": self.event_media_convert_role_arn,
                #"OutputBucket": "" if not isinstance(self.media_convert_output_bucket_name, str) else self.media_convert_output_bucket_name,
                "OutputBucket": self.media_convert_output_bucket_name,
                "MediaConvertMaxInputJobs": "150",
                "MEDIA_CONVERT_ENDPOINT": self.media_convert_endpoint
            },
            layers=[self.mre_workflow_helper_layer]
        )

        self.event_hls_media_convert_job_status_lambda = _lambda.Function(
            self,
            "MreEventHlsMediaConvertJobStatus",
            description="Checks if all MRE Media Convert Jobs for an event are complete",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(f"{RUNTIME_SOURCE_DIR}/lambda/EventHlsManifestGenerator"),
            handler="event_hls_manifest_gen.media_convert_job_status",
            role=self.event_hls_gen_lambda_role,
            memory_size=256,
            timeout=Duration.minutes(5),
            environment={
                "MediaConvertRole": self.event_media_convert_role_arn,
                #"OutputBucket": "" if not isinstance(self.media_convert_output_bucket_name, str) else self.media_convert_output_bucket_name,
                "OutputBucket": self.media_convert_output_bucket_name,
                "MediaConvertMaxInputJobs": "150",
                "MEDIA_CONVERT_ENDPOINT": self.media_convert_endpoint
            },
            layers=[self.mre_workflow_helper_layer]
        )

        ### END: EventHlsGenerator LAMBDA ###

        ### START: EventEdlGenerator LAMBDA ###

        self.event_edl_gen_lambda_role = iam.Role(
            self,
            "MREEventEdlGeneratorIamRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com")
        )

        self.event_edl_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[
                    f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:*"
                ]
            )
        )

        self.event_edl_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:PutObject"
                ],
                resources=[f"arn:aws:s3:::{self.media_convert_output_bucket_name}/*"]
            )
        )

        self.event_edl_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "execute-api:Invoke",
                    "execute-api:ManageConnections"
                ],
                resources=[f"arn:aws:execute-api:{Stack.of(self).region}:{Stack.of(self).account}:*"]
            )
        )

        self.event_edl_gen_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ssm:DescribeParameters",
                    "ssm:GetParameter",
                    "ssm:GetParameters"
                ],
                resources=[f"arn:aws:ssm:{Stack.of(self).region}:{Stack.of(self).account}:parameter/MRE*"]
            )
        )

        self.event_edl_gen_lambda = _lambda.Function(
            self,
            "Mre-ClipGenEventEdlGenerator",
            description="Generates EDL representation for Mre Event",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(f"{RUNTIME_SOURCE_DIR}/lambda/EventEdlGenerator"),
            handler="mre_event_edl_gen.generate_edl",
            role=self.event_edl_gen_lambda_role,
            memory_size=256,
            timeout=Duration.minutes(10),
            environment={
                #"OutputBucket": "" if not isinstance(self.media_convert_output_bucket_name, str) else self.media_convert_output_bucket_name,
                "OutputBucket": self.media_convert_output_bucket_name,
                "MEDIA_CONVERT_ENDPOINT": self.media_convert_endpoint
            },
            layers=[self.mre_workflow_helper_layer,
                    self.mre_plugin_helper_layer,
                    self.timecode_layer
                    ]

        )

        ### END: EventEdlGenerator LAMBDA ###



        # Function: UodateMediaConvertJobStatusInDDB
        self.update_media_convert_job_in_ddb = _lambda.Function(
            self,
            "MRE-ClipGen-UpdateMediaConvertJobStatusInDDB",
            description="MRE - ClipGen - Updates Status of Media Convert Jobs in DDB based on event received from EventBridge",
            runtime=_lambda.Runtime.PYTHON_3_11,
            code=_lambda.Code.from_asset(f"{RUNTIME_SOURCE_DIR}/lambda/EventClipGenerator"),
            handler="mre-event-clip-generator.update_job_status",
            role=self.event_clip_gen_lambda_role,
            memory_size=256,
            timeout=Duration.minutes(1),
            environment={
                "MediaConvertRole": self.event_media_convert_role_arn,
                "OutputBucket": self.media_convert_output_bucket_name,
                "MediaConvertMaxInputJobs": "150",
                "EB_EVENT_BUS_NAME": MRE_EVENT_BUS,
                "MEDIA_CONVERT_ENDPOINT": self.media_convert_endpoint
            },
            layers=[self.mre_workflow_helper_layer,
                    self.mre_plugin_helper_layer
                    ]
        )

        
        # START: Step function definition for ClipGeneration

        # Step Function IAM Role
        self.sfn_clip_gen_role = iam.Role(
            self,
            "EventClipGenerationStepFunctionRole",
            assumed_by=iam.ServicePrincipal(service="states.amazonaws.com"),
            description="Service role for MRE Clip Generation Step Functions"
        )

        
        self.sfn_clip_gen_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                resources=[
                    f"arn:aws:logs:{Stack.of(self).region}:{Stack.of(self).account}:log-group:*"
                ]
            )
        )

        # Step Function IAM Role: Lambda permissions
        self.sfn_clip_gen_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:InvokeFunction"
                ],
                resources=[
                    f"arn:aws:lambda:{Stack.of(self).region}:{Stack.of(self).account}:function:*"
                ]
            )
        )

        self.sfn_clip_gen_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "iam:PassRole"
                ],
                resources=[
                    self.event_media_convert_role_arn
                ]
            )
        )

        generateClipsTask = tasks.LambdaInvoke(
            self,
            "GenerateClips",
            lambda_function=_lambda.Function.from_function_arn(self, 'GenerateClipsLambda',
                                                               self.event_clip_generator_lambda.function_arn),
            retry_on_service_exceptions=True,
            result_path="$.ClipGen"
        )

        getJobStatusTask = tasks.LambdaInvoke(
            self,
            "GetJobStatus",
            lambda_function=_lambda.Function.from_function_arn(self, 'GetJobStatusLambda',
                                                               self.event_hls_media_convert_job_status_lambda.function_arn),
            result_path="$.JobStatus"
        )

        createHlsManifestTask = tasks.LambdaInvoke(
            self,
            "CreateHlsManifest",
            lambda_function=_lambda.Function.from_function_arn(self, 'CreateHlsManifestLambda',
                                                               self.event_hls_create_manifest_lambda.function_arn),
            result_path="$.ClipsGenerated"
        )

        waitTenSecondsTask = sfn.Wait(
            self,
            "wait_10_seconds",
            time=sfn.WaitTime.duration(Duration.seconds(10))
        )

        doneTask = sfn.Pass(
            self,
            "Done",
        )

        definition = generateClipsTask.next(getJobStatusTask.next(sfn.Choice(
            self,
            "AreAllHLSJobsComplete"
        ).when(sfn.Condition.string_equals("$.JobStatus.Payload.Status", "Complete"),
               createHlsManifestTask.next(doneTask)).otherwise(waitTenSecondsTask.next(getJobStatusTask))))

        self.state_machine = sfn.StateMachine(
            self,
            'mre-Event-Clip-Generator-StateMachine',
            definition=definition,
            role=self.sfn_clip_gen_role
        )


        self.event_edl_gen_lambda
        self.mre_edlgen_events_rule = events.Rule(
            self,
            "MREEventEndRule",
            description="Rule that captures the MRE Lifecycle Event SEGMENT_END, OPTIMIZED_SEGMENT_END - Used by Event EDL export",
            enabled=True,
            event_bus=self.event_bus,
            event_pattern=events.EventPattern(
                source=["awsmre"],
                detail={
                    "State":  ["OPTIMIZED_SEGMENT_END", "SEGMENT_END"]
                }
            ),
            targets=[
                events_targets.LambdaFunction(
                    handler=self.event_edl_gen_lambda
                )
            ]
        )
        self.mre_edlgen_events_rule.node.add_dependency(self.event_bus)
        self.mre_edlgen_events_rule.node.add_dependency(self.event_edl_gen_lambda)

        
        self.mre_clipgen_media_convert_job_update_rule = events.Rule(
            self,
            "MREClipGenMediaConvertJobRule",
            description="MRE ClipGen - Rule that captures Event sent from MediaConvert for ClipGen Video Jobs and updates DDB with Job status.",
            enabled=True,
            event_pattern=events.EventPattern(
                source=["aws.mediaconvert"],
                detail={
                    "status": [
                        "COMPLETE","ERROR"
                    ],
                    "userMetadata": {"Source":["ClipGen"]}
                }
            ),
            targets=[
                events_targets.LambdaFunction(
                    handler=self.update_media_convert_job_in_ddb
                )
            ]
        )

        self.mre_clipgen_media_convert_job_update_rule.node.add_dependency(self.update_media_convert_job_in_ddb)

        
        # Store the Clip Gen State Machine ARN
        ssm.StringParameter(
            self,
            "ClipGenStateMachineArn",
            string_value=self.state_machine.state_machine_arn,
            parameter_name="/MRE/ClipGen/StateMachineArn",
            tier=ssm.ParameterTier.INTELLIGENT_TIERING,
            description="[DO NOT DELETE] Contains MRE Clip Generation State Machine Arn"
        )

        CfnOutput(self, "mre-clip-gen", value=self.state_machine.state_machine_arn, description="Contains MRE Clip Generation State Machine Arn", export_name="mre-clip-gen-arn" )

        

        # cdk-nag suppressions
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-DDB3",
                    "reason": "DynamoDB Point-in-time Recovery not required in the default deployment mode. Customers can turn it on if required"
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Chalice role policy requires wildcard permissions for CloudWatch logging, mediaconvert, eventbus, s3",
                    "appliesTo": [
                        
                        f"Resource::arn:aws:logs:<AWS::Region>:<AWS::AccountId>:log-group:*",
                        "Resource::arn:aws:mediaconvert:*:*:*",
                        "Resource::arn:aws:ssm:<AWS::Region>:<AWS::AccountId>:parameter/MRE*",
                        "Resource::arn:aws:mediaconvert:<AWS::Region>:<AWS::AccountId>:jobTemplates/*",
                        "Resource::arn:aws:mediaconvert:<AWS::Region>:<AWS::AccountId>:presets/*",
                        "Resource::arn:aws:mediaconvert:<AWS::Region>:<AWS::AccountId>:queues/*",
                        "Resource::arn:aws:mediaconvert:<AWS::Region>:<AWS::AccountId>:jobs/*",
                        "Resource::arn:aws:events:*:*:event-bus/aws-mre-event-bus",
                        "Resource::arn:aws:execute-api:<AWS::Region>:<AWS::AccountId>:*",
                        "Resource::arn:aws:lambda:<AWS::Region>:<AWS::AccountId>:function:*",
                        {
                            "regex": "/^Resource::arn:aws:s3:::mre*\/*/",
                        },
                        {
                            "regex": "/^Resource::arn:aws:s3:::aws-mre-shared*\/*/",
                        },
                        {
                            "regex": "/^Resource::<MreClipGenEventHlsGenerator*.+Arn>:*/"
                        },
                        {
                            "regex": "/^Resource::<MreEventHlsMediaConvertJobStatus*.+Arn>:*/"
                        },
                        {
                            "regex": "/^Resource::<MreClipGenEventClipGenerator*.+Arn>:*/"
                        }
                    ]
                },
                {
                    "id": "AwsSolutions-SMG4",
                    "reason": "By default no Secrets are created although the keys are created. Customers have to define these if the feature is being used."
                },
                {
                    "id": "AwsSolutions-SF1",
                    "reason": "Lambda functions have logging enabled. Step functions logs are not used"
                },
                {
                    "id": "AwsSolutions-SF2",
                    "reason": "x-Ray Tracing is not used"
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AWS managed policies allowed",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ]
                }
            ]
        )

        NagSuppressions.add_resource_suppressions_by_path(self, 
            f"aws-mre-clip-generation/AWS679f53fac002430cb0da5b7982bd2287", 
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Clip Generator custom resource lambda function does not support the latest runtime version"
                }
            ])

        NagSuppressions.add_resource_suppressions(
            self.event_clip_generator_lambda,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Clip Generator lambda function does not require the latest runtime version"
                }
            ]
        )
        NagSuppressions.add_resource_suppressions(
            self.event_hls_create_manifest_lambda,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "event_hls_create_manifest_lambda lambda function does not require the latest runtime version"
                }
            ]
        )
        NagSuppressions.add_resource_suppressions(
            self.event_hls_media_convert_job_status_lambda,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "event_hls_media_convert_job_status_lambda lambda function does not require the latest runtime version"
                }
            ]
        )
        NagSuppressions.add_resource_suppressions(
            self.event_edl_gen_lambda,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "event_edl_gen_lambda lambda function does not require the latest runtime version"
                }
            ]
        )
        NagSuppressions.add_resource_suppressions(
            self.update_media_convert_job_in_ddb,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "update_media_convert_job_in_ddb lambda function does not require the latest runtime version"
                }
            ]
        )
