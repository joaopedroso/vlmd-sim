# Beginning

I would like to implement a simulator in Python for the following situation.  Assume that some entity provides lockers (e.g.) in subway stations and an APP for dealing with parcel deliveries.  These are done be volunteers, in their daily commutes.  We want to study the span between a parcel being put in the system and being delivered, as a function of the percentage of passengers that act as volunteers.

Data defining an instance is the following.
1. An underlying graph where nodes are stations (assume one locker per station) and arcs correspond to metro legs;
2. Trains' timetable, e.g. in the format of a list of tuples (station,time) for each trip;
3. Origin-destination matrices of commuters along the day (e.g., one matrix per hour; assume values are means, and each variance is 0.1 times the mean);
4. List of parcels to be delivered: parcel_id, release_date, origin, destination, current_locker;

A simulation would be a list of parcel's movements tuples, (parcel_id, volunteer_id, leg, timestamp).

For the time being, assume data is input via text files (e.g., .csv), and provide a small sample for the subway network of Porto, Portugal.

<!-- Read PROBLEM.md. Before writing any code, outline the project structure and approach. I would like to use Python. -->

<!-- Add to the model: -->
<!-- - variance as an attribute of class ODEntry, instead of being hard-coded in generate_volunteers; -->
<!-- - adapt the model to deal with transshipments; -->
<!-- - consider heuristics for "approaching" parcels to their destination: accept any volunteer leg that places the parcel in a locker at less hops of the destination. -->



# Data creation

Before proceeding with the analisis, let us focus on data creation.
For having a solid baseline, I would like to prepare 10 independent passenger OD matrices, based on the previous realistic assumptions.
For each of them, prepare 11 acceptance levels, 0%, 10%, 20%, ..., 100%.
As for parcel origin-destination, consider 1% of the total trips in th passenger's OD; then consider:
   - uniform random parcel OD among all stations in the network;
   - parcel OD positively correlated with passenger OD;
   - parcel OD negatively correlated with passenger OD (worst-case scenario).
