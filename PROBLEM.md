I would like to implement a simulator in Python for the following situation.  Assume that some entity provides lockers (e.g.) in subway stations and an APP for dealing with parcel deliveries.  These are done be volunteers, in their daily commutes.  We want to study the span between a parcel being put in the system and being delivered, as a function of the percentage of passengers that act as volunteers.

Data defining an instance is the following.
1. An underlying graph where nodes are stations (assume one locker per station) and arcs correspond to metro legs;
2. Trains' timetable, e.g. in the format of a list of tuples (station,time) for each trip;
3. Origin-destination matrices of commuters along the day (e.g., one matrix per hour; assume values are means, and each variance is 0.1 times the mean);
4. List of parcels to be delivered: parcel_id, release_date, origin, destination, current_locker;

A simulation would be a list of parcel's movements tuples, (parcel_id, volunteer_id, leg, timestamp).

For the time being, assume data is input via text files (e.g., .csv), and provide a small sample for the subway network of Porto, Portugal.

<!-- Read PROBLEM.md. Before writing any code, outline the project structure and approach. I would like to use Python. -->
