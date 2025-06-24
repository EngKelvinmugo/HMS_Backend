from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q, Max
from django.utils import timezone
from django.shortcuts import get_object_or_404
import datetime
import logging
import json
from django.core.serializers.json import DjangoJSONEncoder
from .filters import TrainerAvailabilityFilter ,TimetableFilter,ClassGroupScheduleFilter

from schoolManager.models import Term

from .models import Room, TrainerAvailability, Timetable, ClassGroupSchedule, TimetableSettings
from .serializers import (
    RoomSerializer,
    TrainerAvailabilitySerializer,
    TimetableSerializer,
    ClassGroupScheduleSerializer,
    TimetableSettingsSerializer,
    TimetableGenerationRequestSerializer
)
from .services import TimetableGenerationService
from .tasks import generate_timetable_async

logger = logging.getLogger('attendance')




class RoomViewSet(viewsets.ModelViewSet):
    """API endpoint for managing rooms."""
    queryset = Room.objects.all()
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['room_type', 'is_active', 'department', 'building', 'floor']
    search_fields = ['name', 'building']
    ordering_fields = ['name', 'capacity', 'building', 'floor']
    ordering = ['building', 'floor', 'name']
    
    def get_serializer_context(self):
        """Add additional context to serializer."""
        context = super().get_serializer_context()
        context['include_schedule'] = self.request.query_params.get('include_schedule', False)
        return context
        
    def get_queryset(self):
        """Filter rooms based on user role and permissions."""
        queryset = super().get_queryset()
        
        # Add annotations for filtering/sorting
        queryset = queryset.annotate(
            session_count=Count('timetable_slots', filter=Q(timetable_slots__is_draft=False))
        )
        
        # Filter by availability status if requested
        available_now = self.request.query_params.get('available_now')
        if available_now and available_now.lower() == 'true':
            # This uses the is_currently_available property logic from the model
            now = timezone.now()
            today_str = now.strftime('%Y-%m-%d')
            current_time = now.time()
            current_day = now.strftime('%A').lower()
            
            queryset = queryset.filter(is_active=True).exclude(
                timetable_slots__day_of_week=current_day,
                timetable_slots__start_time__lte=current_time,
                timetable_slots__end_time__gte=current_time,
                timetable_slots__is_draft=False
            )
        
        return queryset
    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        """Get room availability for a given period."""
        room = self.get_object()
        
        # Get query parameters
        start_date_str = self.request.query_params.get('start_date')
        end_date_str = self.request.query_params.get('end_date')
        
        try:
            # Parse dates
            if start_date_str:
                start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            else:
                start_date = timezone.now().date()
                
            if end_date_str:
                end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                end_date = start_date + datetime.timedelta(days=7)
                
            # Calculate date range
            days = (end_date - start_date).days + 1
            
            # Get all timetable entries for this room during the period
            timetable_entries = Timetable.objects.filter(
                room=room,
                is_draft=False
            ).select_related('course_enrollment__course', 'course_enrollment__trainer', 'course_enrollment__class_group')
            
            # Map weekday names to numbers (0 = Monday, 6 = Sunday)
            day_mapping = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            # Prepare availability data
            availability = []
            
            for day_offset in range(days):
                check_date = start_date + datetime.timedelta(days=day_offset)
                weekday = check_date.weekday()  # 0-6 (Monday to Sunday)
                day_name = list(day_mapping.keys())[weekday]
                
                # Find entries for this weekday
                day_bookings = []
                for entry in timetable_entries:
                    if entry.day_of_week == day_name:
                        # Build session info
                        day_bookings.append({
                            'id': str(entry.id),
                            'start_time': entry.start_time.strftime('%H:%M'),
                            'end_time': entry.end_time.strftime('%H:%M'),
                            'course_name': entry.course_enrollment.course.name,
                            'trainer_name': entry.course_enrollment.trainer.get_full_name() if entry.course_enrollment.trainer else 'No trainer',
                            'class_group': entry.course_enrollment.class_group.name if entry.course_enrollment.class_group else 'No class group',
                        })
                
                # Add day info
                availability.append({
                    'date': check_date.strftime('%Y-%m-%d'),
                    'day_name': day_name.capitalize(),
                    'bookings': day_bookings
                })
                
            return Response(availability)
            
        except (ValueError, TypeError) as e:
            return Response(
                {'detail': f'Invalid date format. Use YYYY-MM-DD format. Error: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class TrainerAvailabilityViewSet(viewsets.ModelViewSet):
    """API endpoint for managing trainer availability."""
    queryset = TrainerAvailability.objects.all()
    serializer_class = TrainerAvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = TrainerAvailabilityFilter
    ordering_fields = ['trainer', 'day_of_week', 'start_time']
    ordering = ['trainer', 'day_of_week', 'start_time']
    
    def get_queryset(self):
        """Filter availability based on user role and permissions."""
        queryset = super().get_queryset()
        user = self.request.user
        # Trainers can only see their own availability
        if user.role == 'trainer':
            queryset = queryset.filter(trainer=user)
           
        return queryset
    
    @action(detail=False, methods=['get'])
    def my_availability(self, request):
        """Get the current user's availability settings."""
        if request.user.role != 'trainer':
            return Response(
                {'detail': 'Only trainers can access this endpoint.'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        queryset = self.get_queryset().filter(trainer=request.user)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """Create multiple availability records at once."""
        if not request.user.is_staff and request.user.role != 'trainer':
            return Response(
                {'detail': 'Permission denied.'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        data = request.data
        if not isinstance(data, list):
            return Response(
                {'detail': 'Expected a list of availability records.'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        created = []
        errors = []
        
        for item in data:
            # If the user is a trainer, ensure they can only create for themselves
            if request.user.role == 'trainer':
                item['trainer'] = request.user.id
                
            serializer = self.get_serializer(data=item)
            if serializer.is_valid():
                serializer.save()
                created.append(serializer.data)
            else:
                errors.append({'data': item, 'errors': serializer.errors})
                
        return Response({
            'created': created,
            'errors': errors
        }, status=status.HTTP_201_CREATED if not errors else status.HTTP_400_BAD_REQUEST)
        

class TimetableViewSet(viewsets.ModelViewSet):
    """API endpoint for managing timetable entries."""
    queryset = Timetable.objects.all()
    serializer_class = TimetableSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = TimetableFilter
    search_fields = ['course_enrollment__course__name','course_enrollment__course__code','course_enrollment__trainer__first_name', 'room__name']
    ordering_fields = ['day_of_week', 'start_time', 'end_time', 'course_enrollment__course__name']
    ordering = ['day_of_week', 'start_time']
    
    def get_queryset(self):
        """Filter timetable entries based on user role and permissions."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Add term filter if provided
        term_id = self.request.query_params.get('term')
        if term_id:
            queryset = queryset.filter(course_enrollment__term_id=term_id)
        
        # Filter by user role
        if user.role == 'trainee':
            # Trainees can only see their class groups' schedules
            queryset = queryset.filter(course_enrollment__class_group__trainees=user)
            queryset = queryset.filter(is_draft=False)  # Only show published entries
        elif user.role == 'trainer':
            # Trainers can see their own assigned classes
            queryset = queryset.filter(course_enrollment__trainer=user)
            queryset = queryset.filter(is_draft=False)  # Only show published entries
        elif user.role == 'hod':
            # HODs can see department-related schedules
            queryset = queryset.filter(
                Q(course_enrollment__course__department__hod=user) |
                Q(course_enrollment__class_group__programme__department__hod=user)
            )
            queryset = queryset.filter(is_draft=False)  # Only show published entries
        elif user.role == 'dp_academics':
            # DP Academics can see all schedules
            queryset = queryset.filter(is_draft=False)  # Only show published entries

        # Select related fields for performance
        queryset = queryset.select_related(
            'course_enrollment__course', 
            'course_enrollment__trainer', 
            'course_enrollment__class_group',
            'room'
        )
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def my_schedule(self, request):
        """Get the current user's schedule."""
        user = request.user
        
        # Get query parameters
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        try:
            # Parse dates
            if start_date_str:
                start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            else:
                start_date = timezone.now().date()
                
            if end_date_str:
                end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                end_date = start_date + datetime.timedelta(days=7)
                
            # Calculate date range
            days = (end_date - start_date).days + 1
            
            # Get appropriate timetable entries
            if user.role == 'trainee':
                timetable_entries = Timetable.objects.filter(
                    course_enrollment__class_group__trainees=user,
                    is_draft=False
                ).select_related('course_enrollment__course', 'course_enrollment__trainer', 'room')
            elif user.role == 'trainer':
                timetable_entries = Timetable.objects.filter(
                    course_enrollment__trainer=user,
                    is_draft=False
                ).select_related('course_enrollment__course', 'course_enrollment__class_group', 'room')
            else:
                return Response(
                    {'detail': 'Schedule view only available for trainees and trainers.'},
                    status=status.HTTP_403_FORBIDDEN
                )
                
            # Map weekday names to numbers (0 = Monday, 6 = Sunday)
            day_mapping = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            # Prepare schedule data
            schedule = []
            
            for day_offset in range(days):
                check_date = start_date + datetime.timedelta(days=day_offset)
                weekday = check_date.weekday()  # 0-6 (Monday to Sunday)
                day_name = list(day_mapping.keys())[weekday]
                
                # Find entries for this weekday
                day_sessions = []
                for entry in timetable_entries:
                    if entry.day_of_week == day_name:
                        # Build session info
                        session_info = {
                            'id': str(entry.id),
                            'start_time': entry.start_time.strftime('%H:%M'),
                            'end_time': entry.end_time.strftime('%H:%M'),
                            'course_name': entry.course_enrollment.course.name,
                            'room_name': entry.room.name,
                            'room_building': entry.room.building,
                        }
                        
                        # Add role-specific information
                        if user.role == 'trainee':
                            session_info['trainer_name'] = entry.course_enrollment.trainer.get_full_name() if entry.course_enrollment.trainer else 'No trainer'
                        elif user.role == 'trainer':
                            session_info['class_group'] = entry.course_enrollment.class_group.name if entry.course_enrollment.class_group else 'No class group'
                            
                        day_sessions.append(session_info)
                
                # Add day info
                schedule.append({
                    'date': check_date.strftime('%Y-%m-%d'),
                    'day_name': day_name.capitalize(),
                    'sessions': day_sessions
                })
                
            return Response(schedule)
            
        except (ValueError, TypeError) as e:
            return Response(
                {'detail': f'Invalid date format. Use YYYY-MM-DD format. Error: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """Create multiple timetable entries at once."""
        if not request.user.is_staff and request.user.role not in ['hod', 'dp_academics']:
            return Response(
                {'detail': 'Permission denied.'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        data = request.data
        if not isinstance(data, list):
            return Response(
                {'detail': 'Expected a list of timetable entries.'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        created = []
        errors = []
        
        for item in data:
            serializer = self.get_serializer(data=item)
            if serializer.is_valid():
                serializer.save()
                created.append(serializer.data)
            else:
                errors.append({'data': item, 'errors': serializer.errors})
                
        return Response({
            'created': created,
            'errors': errors
        }, status=status.HTTP_201_CREATED if not errors else status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a draft timetable entry."""
        timetable = self.get_object()
        
        if not timetable.is_draft:
            return Response(
                {'detail': 'This timetable entry is already published.'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        timetable.is_draft = False
        timetable.save()
        
        serializer = self.get_serializer(timetable)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def revert_to_draft(self, request, pk=None):
        """Revert a published timetable version to draft state using version number."""
        if not request.user.is_staff and request.user.role not in ['hod', 'dp_academics']:
            return Response(
                {'detail': 'Permission denied.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            # pk represents the version number
            draft_version = pk
            
            if not draft_version:
                return Response({
                    'detail': 'No version number provided.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update all published entries with this draft version
            updated_count = Timetable.objects.filter(
                draft_version=draft_version,
                is_draft=False
            ).update(is_draft=True)
            
            if updated_count == 0:
                return Response({
                    'detail': f'No published entries found for version {draft_version}'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Return success response with count of updated entries
            return Response({
                'detail': f'Successfully reverted {updated_count} entries to draft state',
                'updated_count': updated_count,
                'draft_version': draft_version
            })
            
        except Exception as e:
            logger.error(f"Error reverting to draft: {str(e)}", exc_info=True)
            return Response({
                'detail': f'Error reverting to draft: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
    @action(detail=False, methods=['post'])
    def conflicts(self, request):
        """Check for conflicts with existing timetable entries."""
        # Get request data
        data = request.data
        
        try:
            # Extract time values
            start_time = datetime.datetime.strptime(data['start_time'], '%H:%M').time()
            end_time = datetime.datetime.strptime(data['end_time'], '%H:%M').time() 
            
            # Base query for active timetable entries
            conflicts_query = Timetable.objects.filter(
                day_of_week=data['day_of_week'],
                is_draft=False
            ).exclude(id=data.get('id'))

            # Add time overlap conditions
            conflicts_query = conflicts_query.filter(
                Q(start_time__lt=end_time) & Q(end_time__gt=start_time)
            )

            # Check room conflicts
            room_conflicts = conflicts_query.filter(room=data['room'])
            
            # Get the course enrollment directly
            from courseManager.models import Enrollment
            course_enrollment = Enrollment.objects.get(id=data['course_enrollment'])

            # Check trainer conflicts 
            trainer_conflicts = conflicts_query.filter(
                course_enrollment__trainer=course_enrollment.trainer
            )
            
            # Check class group conflicts
            class_group_conflicts = conflicts_query.filter(
                course_enrollment__class_group=course_enrollment.class_group
            )

            conflicts = {
                'has_conflicts': False,
                'room_conflicts': [],
                'trainer_conflicts': [],
                'class_group_conflicts': []
            }

            # Process room conflicts
            if room_conflicts.exists():
                conflicts['has_conflicts'] = True
                conflicts['room_conflicts'] = [{
                    'id': c.id,
                    'course': c.course_enrollment.course.name,
                    'start_time': c.start_time.strftime('%H:%M'),
                    'end_time': c.end_time.strftime('%H:%M'),
                    'room': c.room.name
                } for c in room_conflicts]

            # Process trainer conflicts
            if trainer_conflicts.exists():
                conflicts['has_conflicts'] = True
                conflicts['trainer_conflicts'] = [{
                    'id': c.id,
                    'course': c.course_enrollment.course.name,
                    'trainer': c.course_enrollment.trainer.get_full_name(),
                    'start_time': c.start_time.strftime('%H:%M'),
                    'end_time': c.end_time.strftime('%H:%M')
                } for c in trainer_conflicts]

            # Process class group conflicts
            if class_group_conflicts.exists():
                conflicts['has_conflicts'] = True
                conflicts['class_group_conflicts'] = [{
                    'id': c.id,
                    'course': c.course_enrollment.course.name,
                    'class_group': c.course_enrollment.class_group.name,
                    'start_time': c.start_time.strftime('%H:%M'),
                    'end_time': c.end_time.strftime('%H:%M')
                } for c in class_group_conflicts]

            return Response(conflicts)

        except Exception as e:
            return Response(
                {'detail': f'Error checking conflicts: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    def check_for_conflicts(self, timetable_data):
        """
        Helper function to check for conflicts using the existing conflicts action.
        
        Args:
            timetable_data: Dictionary containing timetable entry data
            
        Returns:
            tuple: (has_conflicts, conflicts_data)
        """
        # Create a new request object with the timetable data
        from rest_framework.test import APIRequestFactory
        factory = APIRequestFactory()
        conflicts_request = factory.post('/timetable/conflicts/', timetable_data, format='json')
        
        # Add user to request
        conflicts_request.user = self.request.user
        
        # Use the existing conflicts action to check for conflicts
        conflicts_view = self.conflicts(conflicts_request)
        
        if conflicts_view.status_code != status.HTTP_200_OK:
            # Handle error case
            return True, {'error': 'Failed to check conflicts', 'details': conflicts_view.data}
        
        # Return the conflict status and data
        return conflicts_view.data.get('has_conflicts', False), conflicts_view.data
    
    @action(detail=False, methods=['get'])
    def draft_versions(self, request):
        """
        Get list of available draft versions.
        
        This returns comprehensive information about all draft versions in the system,
        including their status (active/draft), entry counts, and associated metadata.
        
        Query parameters:
            term_id: Optional filter by term ID
            include_empty: Include versions with no entries (default: false)
            show_all: Show all versions including those with no draft entries (default: false)
        """
        # Get query parameters
        term_id = request.query_params.get('term_id')
        include_empty = request.query_params.get('include_empty', 'false').lower() == 'true'
        
        # Base filter conditions
        version_filter = ~Q(draft_version__isnull=True) & ~Q(draft_version__exact='')
        term_filter = Q(course_enrollment__term_id=term_id) if term_id else Q()
        
        
        # Get all unique draft versions
        all_versions = (
            Timetable.objects
            .filter(version_filter, term_filter)
            .exclude(draft_version__isnull=True)
            .exclude(draft_version__exact='')
            .values('draft_version')
            .annotate(latest_created=Max('created_at'))
            .order_by('-latest_created')
        )

        print(f'All versions: {all_versions}')
        
        # Use TimetableGenerationService to get comprehensive status for each version
        from .services import TimetableGenerationService
        
        # Build detailed information for each version
        result = []
        for draft in all_versions:
            version = draft['draft_version']
            if not version:
                continue
                
            # Get status for this draft version
            status = TimetableGenerationService.get_draft_version_status(version, term_id)
            
            # Skip empty versions unless specifically requested
            if not include_empty and status['total_entries'] == 0:
                continue
                
            # Get all entries for this version
            entries = Timetable.objects.filter(draft_version=version)
            if not entries.exists():
                continue
                
            # Get first entry for metadata
            first_entry = entries.select_related(
                'course_enrollment__term',
                'course_enrollment__class_group__programme__department'
            ).first()
            
            if first_entry:
                # Build version info with the status info
                result.append({
                    'version': version,
                    'created_at': first_entry.created_at,
                    'term': str(first_entry.course_enrollment.term),
                    'total_entries': status['total_entries'],
                    'draft_entries': status['draft_entries'],
                    'published_entries': status['published_entries'],
                    'is_active': status['is_active'],
                    'active_version': status['active_version'],
                    'departments': list(set(
                        entry.course_enrollment.class_group.programme.department.name
                        for entry in entries.select_related(
                            'course_enrollment__class_group__programme__department'
                        )
                        if entry.course_enrollment.class_group.programme.department
                    ))                })
        
        return Response(result)    
    @action(detail=False, methods=['post'])
    def publish_draft(self, request):
        """
        Publish all timetable entries with a specific draft version.
        
        This endpoint ensures only one active version exists at a time by
        reverting any currently active versions to draft state before
        publishing the new version.
        """
        version = request.data.get('draft_version')
        if not version:
            return Response({
                'detail': 'No draft version specified'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Use the TimetableGenerationService to publish the draft
        # This ensures we follow the "one active version" rule
        try:
            # Create service instance for this operation
            tgs = TimetableGenerationService()

            # deactivate any currently active versions
            active_versions = Timetable.objects.filter(
                is_draft=False,
            ).update(is_draft=True)
            if active_versions > 0:
                # Log the deactivation of active versions
                logger.info(f'Deactivated {active_versions} active timetable entries.')

            # Publish the draft version
            result = tgs.publish_draft_timetable(draft_version=version)
            
            # Check the result
            if result['published_count'] == 0:
                return Response({
                    'detail': f'No draft entries found for version {version}'
                }, status=status.HTTP_404_NOT_FOUND)
                
            # Successful publish
            response_data = {
                'published_count': result['published_count'],
                'message': f'Successfully published {result["published_count"]} timetable entries.'
            }
            
            # Include info about previously active versions if any were reverted
            if result['previously_active_count'] > 0:
                response_data['previously_active_count'] = result['previously_active_count']
                response_data['previously_active_versions'] = result['previously_active_versions']
                response_data['message'] += f' Reverted {result["previously_active_count"]} entries from previously active versions.'
                
            # Get a list of unique class groups from the published entries
            published_entries = Timetable.objects.filter(
                draft_version=version,
                is_draft=False
            ).select_related('course_enrollment__class_group')
            
            # Collect unique class groups
            class_groups = set()
            for entry in published_entries:
                if entry.course_enrollment and entry.course_enrollment.class_group:
                    class_groups.add(entry.course_enrollment.class_group)
            
            # Update class group schedules if needed
            if class_groups:
                from .models import ClassGroupSchedule
                for class_group in class_groups:
                    term = Term.get_current_term()
                    ClassGroupSchedule.update_or_create_schedule(class_group, term)

                response_data['updated_class_groups'] = len(class_groups)
            
            return Response(response_data)
            
        except ValueError as e:
            return Response({
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        
    @action(detail=False, methods=['post'])
    def discard_draft(self, request):
        """
        Discard all draft timetable entries with a specific draft version.
        
        This operation only affects entries that are still in draft state (is_draft=True).
        Published entries with this draft version will not be affected.
        
        Returns information about both draft and published entries for this version.
        """
        version = request.data.get('draft_version')
        if not version:
            return Response({
                'detail': 'No draft version specified'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Use the service to discard draft entries
        try:
            # Create service instance
            tgs = TimetableGenerationService()
            
            # Discard draft entries
            result = tgs.discard_draft_timetable(draft_version=version)
            
            if result['discarded_count'] == 0:
                return Response({
                    'detail': f'No draft entries found for version {version}'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Return comprehensive information about the operation
            return Response({
                'detail': f'Successfully discarded {result["discarded_count"]} draft timetable entries for version {version}',
                'discarded_count': result['discarded_count'],
                'published_entries_remaining': result['published_entries_remaining'],
                'is_active': result['is_active'],
                'version_status': result['post_status']
            })
        except Exception as e:
            return Response({
                'detail': f'Error discarding draft: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response(response_data)
    @action(detail=False, methods=['get'])
    def draft_summary(self, request):
        """
        Get detailed summary of a specific draft version.
        
        This endpoint provides a comprehensive view of a draft version,
        which represents a complete timetable generation rather than individual entries.
        
        The returned data includes:
        - Version information and status
        - Entry counts (total, draft, published)
        - Term and creation date
        - Department and class group distribution
        - Active status and conflicts with other versions
        """
        version = request.query_params.get('draft_version')
        term_id = request.query_params.get('term_id')
        
        if not version:
            return Response({
                'detail': 'No draft version specified'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Use the service to get comprehensive version status
        from .services import TimetableGenerationService
        version_status = TimetableGenerationService.get_draft_version_status(version, term_id)
        
        if version_status['total_entries'] == 0:
            return Response({
                'detail': f'No entries found for version {version}'
            }, status=status.HTTP_404_NOT_FOUND)
            
        # Get all timetable entries with this version (both draft and published)
        entries = Timetable.objects.filter(
            draft_version=version
        ).select_related(
            'course_enrollment__course',
            'course_enrollment__class_group',
            'course_enrollment__class_group__programme__department',
            'course_enrollment__trainer',
            'room'
        )
          # Prepare summary data
        first_entry = entries.first()
        term = first_entry.course_enrollment.term
        
        # Merge version status with other information
        summary = {
            'version': version,
            'created_at': first_entry.created_at,
            'term': str(term),
            'total_entries': version_status['total_entries'],
            'draft_entries': version_status['draft_entries'],
            'published_entries': version_status['published_entries'],
            'is_active': version_status['is_active'],
            'active_version': version_status['active_version'],
            'departments': {},
            'class_groups': {},
            'days': {},
            'trainers': {},
            'rooms': {}
        }
        
        # Group entries by various attributes
        for entry in entries:
            # By department
            dept = entry.course_enrollment.class_group.programme.department
            if dept:
                dept_id = str(dept.id)
                if dept_id not in summary['departments']:
                    summary['departments'][dept_id] = {
                        'name': dept.name,
                        'entry_count': 0
                    }
                summary['departments'][dept_id]['entry_count'] += 1
                
            # By class group
            cg = entry.course_enrollment.class_group
            cg_id = str(cg.id)
            if cg_id not in summary['class_groups']:
                summary['class_groups'][cg_id] = {
                    'name': cg.name,
                    'department': dept.name if dept else 'Unassigned',
                    'entry_count': 0
                }
            summary['class_groups'][cg_id]['entry_count'] += 1
            
            # By day
            day = entry.day_of_week
            if day not in summary['days']:
                summary['days'][day] = 0
            summary['days'][day] += 1
            
            # By trainer
            trainer = entry.course_enrollment.trainer
            if trainer:
                trainer_id = str(trainer.id)
                if trainer_id not in summary['trainers']:
                    summary['trainers'][trainer_id] = {
                        'name': trainer.get_full_name(),
                        'entry_count': 0
                    }
                summary['trainers'][trainer_id]['entry_count'] += 1
                
            # By room
            room = entry.room
            if room:
                room_id = str(room.id)
                if room_id not in summary['rooms']:
                    summary['rooms'][room_id] = {
                        'name': room.name,
                        'entry_count': 0
                    }
                summary['rooms'][room_id]['entry_count'] += 1
        
        return Response(summary)


class ClassGroupScheduleViewSet(viewsets.ModelViewSet):
    """API endpoint for managing class group schedules."""
    queryset = ClassGroupSchedule.objects.all()
    serializer_class = ClassGroupScheduleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ClassGroupScheduleFilter
    ordering_fields = ['class_group__name', 'term__name', 'last_updated']
    ordering = ['-last_updated']

    def get_queryset(self):
        """Filter class group schedules based on user role and permissions."""
        queryset = super().get_queryset()
        user = self.request.user
        
        # Filter by user role
        if user.role == 'trainee':
            # Trainees can only see their class groups' schedules
            queryset = queryset.filter(class_group__trainees=user)
        elif user.role == 'trainer':
            # Trainers can see schedules for class groups they teach
            queryset = queryset.filter(
                class_group__in=ClassGroup.objects.filter(
                    programme__enrollments__trainer=user
                ).distinct()
            )
        elif user.role == 'hod':
            # HODs can see department-related schedules
            queryset = queryset.filter(class_group__programme__department__hod=user)
        
        # Select related fields for performance
        queryset = queryset.select_related('class_group', 'term')
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def regenerate(self, request, pk=None):
        """Regenerate the schedule for a class group."""
        schedule = self.get_object()
        
        try:
            ClassGroupSchedule.update_or_create_schedule(
                schedule.class_group,
                schedule.term
            )
            
            # Get the updated object
            updated_schedule = ClassGroupSchedule.objects.get(pk=schedule.pk)
            serializer = self.get_serializer(updated_schedule)
            return Response(serializer.data)
            
        except Exception as e:
            return Response(
                {'detail': f'Error regenerating schedule: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class TimetableSettingsViewSet(viewsets.ModelViewSet):
    """API endpoint for managing timetable generation settings."""
    queryset = TimetableSettings.objects.all()
    serializer_class = TimetableSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['term', 'school']
    ordering_fields = ['term__name', 'school__name', 'updated_at']
    ordering = ['-updated_at']
    
    def get_permissions(self):
        """Ensure only staff and admins can modify settings."""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


class TimetableGenerationViewSet(viewsets.ViewSet):
    """API endpoint for timetable generation."""
    permission_classes = [permissions.IsAuthenticated]
    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Generate a timetable using backtracking algorithm."""
        # Check permissions
        if not request.user.is_staff and request.user.role not in ['hod', 'dp_academics']:
            return Response(
                {'detail': 'Permission denied.'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # Validate request data
        serializer = TimetableGenerationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        validated_data = serializer.validated_data
        
        # Check if this should be processed asynchronously
        async_generation = request.query_params.get('async', 'false').lower() == 'true'
        
        if async_generation:
            # Start asynchronous task
            try:                
                # Make sure we extract actual values from the validated data
                term_id = str(validated_data.get('term_id')) if validated_data.get('term_id') else None
                class_group_ids = [str(id) for id in validated_data.get('class_group_ids', [])]
                department_ids = [str(id) for id in validated_data.get('department_ids', [])]
                school_id = str(validated_data.get('school_id')) if validated_data.get('school_id') else None
                create_entries = validated_data.get('create_entries', True)
                user_id = str(request.user.id)
                
                task = generate_timetable_async.delay(
                    term_id=term_id,
                    class_group_ids=class_group_ids,
                    department_ids=department_ids,
                    school_id=school_id,
                    create_entries=create_entries,
                    user_id=user_id
                )
                
                return Response({
                    'detail': 'Timetable generation has been started.',
                    'task_id': str(task.id)
                })
            except Exception as e:
                logger.error(f"Error starting async timetable generation: {str(e)}", exc_info=True)
                return Response({
                    'detail': f'Error starting timetable generation: {str(e)}',
                    'error': str(e)
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            # Process synchronously
            try:                
                # Initialize the service
                service = TimetableGenerationService(
                    term_id=validated_data.get('term_id'),
                    class_group_ids=validated_data.get('class_group_ids'),
                    department_ids=validated_data.get('department_ids'),
                    school_id=validated_data.get('school_id')
                )
                
                # Generate the timetable
                success = service.generate_timetable()
                
                # Get report
                report = service.get_report()
                if success and validated_data.get('create_entries', True):
                    # Create timetable entries with enhanced error handling
                    try:
                        created_count = service.create_timetable_entries()
                        report['created_count'] = created_count
                        
                        # Include any failure details from the service
                        if hasattr(service, '_failure_entries') and service._failure_entries:
                            report['failed_entries'] = {
                                'count': len(service._failure_entries),
                                'details': service._failure_entries[:10] if len(service._failure_entries) > 10 else service._failure_entries,
                                'has_more': len(service._failure_entries) > 10,
                                'total': len(service._failure_entries)
                            }
                            logger.warning(f"Some timetable entries failed to create: {len(service._failure_entries)} failures")
                    
                    except RuntimeError as re:
                        # Handle specific runtime errors from create_timetable_entries
                        logger.error(f"Critical error creating timetable entries: {str(re)}")
                        report['error'] = str(re)
                        report['created_count'] = 0
                        
                        # Add structured error information for API consumers
                        if "failed_entries" in report:
                            report['error_details'] = report['failed_entries']
                        else:
                            report['error_details'] = {'message': str(re)}
                        
                        # We consider this a partial success - timetable was generated but entries weren't created
                        success = False
                        
                    except ValueError as ve:
                        # Handle validation errors
                        logger.error(f"Validation error creating timetable entries: {str(ve)}")
                        report['error'] = str(ve)
                        report['created_count'] = 0
                        success = False
                    
                # Update class group schedules only if entries were created
                created_count = 0
                if success:
                    if isinstance(report.get('created_count'), dict):
                        created_count = report.get('created_count', {}).get('count', 0)
                    else:
                        created_count = report.get('created_count', 0)
                        
                if success and created_count > 0:
                    from schoolManager.models import ClassGroup
                    schedule_updates_succeeded = 0
                    schedule_updates_failed = 0
                    
                    for class_group_id in validated_data.get('class_group_ids', []):
                        try:
                            class_group = ClassGroup.objects.get(pk=class_group_id)
                            ClassGroupSchedule.update_or_create_schedule(class_group, service.term)
                            schedule_updates_succeeded += 1
                        except Exception as e:
                            schedule_updates_failed += 1
                            logger.error(f"Error updating schedule for class group {class_group_id}: {str(e)}")
                    
                    report['schedule_updates'] = {
                        'succeeded': schedule_updates_succeeded,
                        'failed': schedule_updates_failed
                    }
                
                # Determine response status code based on outcome
                response_status = status.HTTP_200_OK
                if not success:
                    if 'error' in report and 'No timetable has been generated' in report['error']:
                        response_status = status.HTTP_400_BAD_REQUEST
                    elif report.get('created_count', 0) == 0:
                        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY  # Semantic error
                    else:
                        response_status = status.HTTP_207_MULTI_STATUS  # Partial success
                
                return Response({
                    'success': success,
                    'report': report
                }, status=response_status)
                
            except Exception as e:
                logger.error(f"Error in synchronous timetable generation: {str(e)}", exc_info=True)
                error_type = type(e).__name__
                
                # Provide more specific error responses based on the exception type
                if error_type == 'ValueError':
                    # Input validation errors
                    return Response({
                        'detail': f'Invalid input for timetable generation: {str(e)}',
                        'error': str(e),
                        'error_type': error_type
                    }, status=status.HTTP_400_BAD_REQUEST)
                elif error_type in ['ObjectDoesNotExist', 'DoesNotExist']:
                    # Missing reference errors
                    return Response({
                        'detail': f'Referenced object not found: {str(e)}',
                        'error': str(e),
                        'error_type': error_type
                    }, status=status.HTTP_404_NOT_FOUND)
                else:
                    # General server errors
                    return Response({
                        'detail': f'Error generating timetable: {str(e)}',
                        'error': str(e),
                        'error_type': error_type
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    @action(detail=False, methods=['get'])
    def task_status(self, request):
        """Check the status of an asynchronous timetable generation task."""
        task_id = request.query_params.get('task_id')
        if not task_id:
            return Response(
                {'detail': 'task_id parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            from celery.result import AsyncResult
            
            result = AsyncResult(task_id)
            
            if result.state == 'PENDING':
                response = {
                    'state': result.state,
                    'status': 'Task is pending execution.'
                }
            elif result.state == 'FAILURE':
                response = {
                    'state': result.state,
                    'status': 'Task has failed.',
                    'error': str(result.info) if result.info else 'Unknown error'
                }
            elif result.state == 'PROGRESS':
                response = {
                    'state': result.state,
                    'status': 'Task is in progress.',
                    'progress': result.info
                }
                
                # Add progress info if available
                if isinstance(result.info, dict) and 'current' in result.info and 'total' in result.info:
                    response['progress_percentage'] = int((result.info['current'] / result.info['total']) * 100)
            else:  # SUCCESS or other states
                response = {
                    'state': result.state,
                    'status': 'Task is complete.',
                }
                
                # Include the actual result if available
                if result.ready():
                    try:
                        task_result = result.get()
                        if isinstance(task_result, dict):
                            response.update(task_result)
                        else:
                            response['result'] = task_result
                    except Exception as e:
                        response['error'] = f"Error retrieving task result: {str(e)}"
                    
            return Response(response)
                
        except Exception as e:
            logger.error(f"Error checking task status: {str(e)}", exc_info=True)
            return Response(
                {'detail': f'Error checking task status: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    @action(detail=False, methods=['post'])
    def validate_timetable_entry(self, request):
        """
        Validate a timetable entry for conflicts before creating/updating.
        
        This endpoint checks if a proposed timetable entry would cause conflicts
        without actually saving it to the database.
        """
        # Get data from request
        data = request.data
        
        # Validate required fields
        required_fields = ['start_time', 'end_time', 'day_of_week', 'room', 'course_enrollment']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return Response(
                {'detail': f'Missing required fields: {", ".join(missing_fields)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check for conflicts using our helper function
        has_conflicts, conflicts_data = self.check_for_conflicts(data)
        
        if has_conflicts:
            # Return the conflicts without saving the entry
            return Response({
                'valid': False,
                'message': 'This timetable entry would create conflicts',
                'conflicts': conflicts_data
            })
        
        # No conflicts found
        return Response({
            'valid': True,
            'message': 'No conflicts detected for this timetable entry'
        })
    
