import logging
from typing import Optional, Type, List
from utils.settings import settings
from .tv_base import TVControlBase
from ..implementations import AndroidTV, TizenTV, WebOSTV

logger = logging.getLogger(__name__)

class TVFactory:
    """Factory for creating TV controller instances"""

    # Map of TV types to their controller classes
    TV_TYPES = {
        'android': {
            'sony': AndroidTV
        },
        'tizen': {
            'samsung': TizenTV
        },
        'webos': {
            'lg': WebOSTV
        }
    }

    @classmethod
    def get_all_tv_controllers(cls) -> List[TVControlBase]:
        """
        Create TV controllers for all configured TVs
        Returns:
            List[TVControlBase]: List of TV controller instances
        """
        controllers = []
        try:
            # Get dynamic TV configurations
            tv_settings = settings.get('clients', {}).get('tvs', {}).get('instances', {})
            for tv_name, tv_config in tv_settings.items():
                if tv_config.get('enabled', True):  # enabled by default
                    tv_type = tv_config.get('type')
                    tv_model = tv_config.get('model')

                    controller = cls._create_controller(tv_type, tv_model, tv_config)
                    if controller:
                        controllers.append(controller)

        except Exception as e:
            logger.error(f"Error creating TV controllers: {e}")

        return controllers

    @classmethod
    def get_tv_controller(cls, tv_name: Optional[str] = None) -> Optional[TVControlBase]:
        """
        Create a TV controller based on configuration
        Args:
            tv_name: Optional name of specific TV to get controller for
        Returns:
            TVControlBase: TV controller instance or None if not configured
        """
        try:
            # If no specific TV requested, return first available
            if not tv_name:
                controllers = cls.get_all_tv_controllers()
                return controllers[0] if controllers else None

            # Get specific TV configuration
            tv_settings = settings.get('clients', {}).get('tvs', {}).get('instances', {})
            tv_config = tv_settings.get(tv_name, {})

            if tv_config.get('enabled', True):
                return cls._create_controller(
                    tv_config.get('type'),
                    tv_config.get('model'),
                    tv_config
                )

        except Exception as e:
            logger.error(f"Error creating TV controller: {e}")

        return None

    @classmethod
    def _create_controller(cls, tv_type: str, tv_model: str, config: dict) -> Optional[TVControlBase]:
        """
        Create a TV controller instance based on type and model
        Args:
            tv_type: Type of TV (webos/tizen/android)
            tv_model: Model of TV (lg/samsung/sony)
            config: TV configuration dictionary
        Returns:
            TVControlBase: TV controller instance or None if invalid config
        """
        if not tv_type:
            logger.error("TV type not specified in settings")
            return None

        # Derive model from type if not provided
        if not tv_model:
            model_mapping = {
                'webos': 'lg',
                'tizen': 'samsung',
                'android': 'sony'
            }
            tv_model = model_mapping.get(tv_type)
            if not tv_model:
                logger.error(f"Could not derive model for TV type: {tv_type}")
                return None

        # Get the appropriate controller class
        controller_class = cls.TV_TYPES.get(tv_type, {}).get(tv_model)
        if not controller_class:
            logger.error(f"No controller found for TV type '{tv_type}' and model '{tv_model}'")
            return None

        # Create controller instance
        try:
            return controller_class(
                ip=config.get('ip'),
                mac=config.get('mac')
            )
        except Exception as e:
            logger.error(f"Error creating controller instance: {e}")
            return None

    @classmethod
    def get_supported_types(cls) -> dict:
        """Get list of supported TV types and models"""
        return cls.TV_TYPES

    @classmethod
    def get_controller_class(cls, tv_type: str, model: str) -> Optional[Type[TVControlBase]]:
        """Get controller class for specific TV type and model"""
        return cls.TV_TYPES.get(tv_type, {}).get(model)
