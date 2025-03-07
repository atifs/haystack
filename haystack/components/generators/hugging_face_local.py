import logging
from typing import Any, Dict, List, Literal, Optional

from haystack import component, default_from_dict, default_to_dict

from haystack.lazy_imports import LazyImport
from haystack.utils import ComponentDevice
from haystack.utils.hf import deserialize_hf_model_kwargs, serialize_hf_model_kwargs
from haystack.utils import Secret, deserialize_secrets_inplace

logger = logging.getLogger(__name__)

SUPPORTED_TASKS = ["text-generation", "text2text-generation"]

with LazyImport(message="Run 'pip install transformers[torch]'") as transformers_import:
    from huggingface_hub import model_info
    from transformers import StoppingCriteriaList, pipeline
    from haystack.utils.hf import StopWordsCriteria  # pylint: disable=ungrouped-imports


@component
class HuggingFaceLocalGenerator:
    """
    Generator based on a Hugging Face model.

    This component provides an interface to generate text using a Hugging Face model that runs locally.

    Usage example:
    ```python
    from haystack.components.generators import HuggingFaceLocalGenerator

    generator = HuggingFaceLocalGenerator(
        model="google/flan-t5-large",
        task="text2text-generation",
        generation_kwargs={"max_new_tokens": 100, "temperature": 0.9})

    print(generator.run("Who is the best American actor?"))
    # {'replies': ['John Cusack']}
    ```
    """

    def __init__(
        self,
        model: str = "google/flan-t5-base",
        task: Optional[Literal["text-generation", "text2text-generation"]] = None,
        device: Optional[ComponentDevice] = None,
        token: Optional[Secret] = Secret.from_env_var("HF_API_TOKEN", strict=False),
        generation_kwargs: Optional[Dict[str, Any]] = None,
        huggingface_pipeline_kwargs: Optional[Dict[str, Any]] = None,
        stop_words: Optional[List[str]] = None,
    ):
        """
        Creates an instance of a HuggingFaceLocalGenerator.

        :param model: The name or path of a Hugging Face model for text generation,
        :param task: The task for the Hugging Face pipeline.
            Possible values are "text-generation" and "text2text-generation".
            Generally, decoder-only models like GPT support "text-generation",
            while encoder-decoder models like T5 support "text2text-generation".
            If the task is also specified in the `huggingface_pipeline_kwargs`, this parameter will be ignored.
            If not specified, the component will attempt to infer the task from the model name,
            calling the Hugging Face Hub API.
        :param device: The device on which the model is loaded. If `None`, the default device is automatically
            selected. If a device/device map is specified in `huggingface_pipeline_kwargs`, it overrides this parameter.
        :param token: The token to use as HTTP bearer authorization for remote files.
            If the token is also specified in the `huggingface_pipeline_kwargs`, this parameter will be ignored.
        :param generation_kwargs: A dictionary containing keyword arguments to customize text generation.
            Some examples: `max_length`, `max_new_tokens`, `temperature`, `top_k`, `top_p`,...
            See Hugging Face's documentation for more information:
            - [customize-text-generation](https://huggingface.co/docs/transformers/main/en/generation_strategies#customize-text-generation)
            - [transformers.GenerationConfig](https://huggingface.co/docs/transformers/main/en/main_classes/text_generation#transformers.GenerationConfig)
        :param huggingface_pipeline_kwargs: Dictionary containing keyword arguments used to initialize the
            Hugging Face pipeline for text generation.
            These keyword arguments provide fine-grained control over the Hugging Face pipeline.
            In case of duplication, these kwargs override `model`, `task`, `device`, and `token` init parameters.
            See Hugging Face's [documentation](https://huggingface.co/docs/transformers/en/main_classes/pipelines#transformers.pipeline.task)
            for more information on the available kwargs.
            In this dictionary, you can also include `model_kwargs` to specify the kwargs for model initialization:
            [transformers.PreTrainedModel.from_pretrained](https://huggingface.co/docs/transformers/en/main_classes/model#transformers.PreTrainedModel.from_pretrained)
        :param stop_words: A list of stop words. If any one of the stop words is generated, the generation is stopped.
            If you provide this parameter, you should not specify the `stopping_criteria` in `generation_kwargs`.
            For some chat models, the output includes both the new text and the original prompt.
            In these cases, it's important to make sure your prompt has no stop words.
        """
        transformers_import.check()

        huggingface_pipeline_kwargs = huggingface_pipeline_kwargs or {}
        generation_kwargs = generation_kwargs or {}

        self.token = token
        token = token.resolve_value() if token else None

        # check if the huggingface_pipeline_kwargs contain the essential parameters
        # otherwise, populate them with values from other init parameters
        huggingface_pipeline_kwargs.setdefault("model", model)
        huggingface_pipeline_kwargs.setdefault("token", token)

        device = ComponentDevice.resolve_device(device)
        device.update_hf_kwargs(huggingface_pipeline_kwargs, overwrite=False)

        # task identification and validation
        if task is None:
            if "task" in huggingface_pipeline_kwargs:
                task = huggingface_pipeline_kwargs["task"]
            elif isinstance(huggingface_pipeline_kwargs["model"], str):
                task = model_info(
                    huggingface_pipeline_kwargs["model"], token=huggingface_pipeline_kwargs["token"]
                ).pipeline_tag

        if task not in SUPPORTED_TASKS:
            raise ValueError(
                f"Task '{task}' is not supported. " f"The supported tasks are: {', '.join(SUPPORTED_TASKS)}."
            )
        huggingface_pipeline_kwargs["task"] = task

        # if not specified, set return_full_text to False for text-generation
        # only generated text is returned (excluding prompt)
        if task == "text-generation":
            generation_kwargs.setdefault("return_full_text", False)

        if stop_words and "stopping_criteria" in generation_kwargs:
            raise ValueError(
                "Found both the `stop_words` init parameter and the `stopping_criteria` key in `generation_kwargs`. "
                "Please specify only one of them."
            )

        self.huggingface_pipeline_kwargs = huggingface_pipeline_kwargs
        self.generation_kwargs = generation_kwargs
        self.stop_words = stop_words
        self.pipeline = None
        self.stopping_criteria_list = None

    def _get_telemetry_data(self) -> Dict[str, Any]:
        """
        Data that is sent to Posthog for usage analytics.
        """
        if isinstance(self.huggingface_pipeline_kwargs["model"], str):
            return {"model": self.huggingface_pipeline_kwargs["model"]}
        return {"model": f"[object of type {type(self.huggingface_pipeline_kwargs['model'])}]"}

    def warm_up(self):
        """
        Initializes the component.
        """
        if self.pipeline is None:
            self.pipeline = pipeline(**self.huggingface_pipeline_kwargs)

        if self.stop_words and self.stopping_criteria_list is None:
            stop_words_criteria = StopWordsCriteria(
                tokenizer=self.pipeline.tokenizer, stop_words=self.stop_words, device=self.pipeline.device
            )
            self.stopping_criteria_list = StoppingCriteriaList([stop_words_criteria])

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the component to a dictionary.

        :returns:
            Dictionary with serialized data.
        """
        serialization_dict = default_to_dict(
            self,
            huggingface_pipeline_kwargs=self.huggingface_pipeline_kwargs,
            generation_kwargs=self.generation_kwargs,
            stop_words=self.stop_words,
            token=self.token.to_dict() if self.token else None,
        )

        huggingface_pipeline_kwargs = serialization_dict["init_parameters"]["huggingface_pipeline_kwargs"]
        huggingface_pipeline_kwargs.pop("token", None)

        serialize_hf_model_kwargs(huggingface_pipeline_kwargs)
        return serialization_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HuggingFaceLocalGenerator":
        """
        Deserializes the component from a dictionary.

        :param data:
            The dictionary to deserialize from.
        :returns:
            The deserialized component.
        """
        deserialize_secrets_inplace(data["init_parameters"], keys=["token"])
        deserialize_hf_model_kwargs(data["init_parameters"]["huggingface_pipeline_kwargs"])
        return default_from_dict(cls, data)

    @component.output_types(replies=List[str])
    def run(self, prompt: str, generation_kwargs: Optional[Dict[str, Any]] = None):
        """
        Run the text generation model on the given prompt.

        :param prompt:
            A string representing the prompt.
        :param generation_kwargs:
            Additional keyword arguments for text generation.

        :returns:
            A dictionary containing the generated replies.
            - replies: A list of strings representing the generated replies.
        """
        if self.pipeline is None:
            raise RuntimeError("The generation model has not been loaded. Please call warm_up() before running.")

        if not prompt:
            return {"replies": []}

        # merge generation kwargs from init method with those from run method
        updated_generation_kwargs = {**self.generation_kwargs, **(generation_kwargs or {})}

        output = self.pipeline(prompt, stopping_criteria=self.stopping_criteria_list, **updated_generation_kwargs)
        replies = [o["generated_text"] for o in output if "generated_text" in o]

        if self.stop_words:
            # the output of the pipeline includes the stop word
            replies = [reply.replace(stop_word, "").rstrip() for reply in replies for stop_word in self.stop_words]

        return {"replies": replies}
