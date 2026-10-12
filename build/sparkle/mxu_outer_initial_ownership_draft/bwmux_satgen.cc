	if (cell->type.in(ID($_MUX_), ID($mux), ID($_NMUX_), ID($bwmux)))
	{
		std::vector<int> a = importDefSigSpec(cell->getPort(ID::A), timestep);
		std::vector<int> b = importDefSigSpec(cell->getPort(ID::B), timestep);
		std::vector<int> s = importDefSigSpec(cell->getPort(ID::S), timestep);
		std::vector<int> y = importDefSigSpec(cell->getPort(ID::Y), timestep);

		std::vector<int> yy = model_undef ? ez->vec_var(y.size()) : y;
		if (cell->type == ID($_NMUX_))
			ez->assume(ez->vec_eq(ez->vec_not(ez->vec_ite(s.at(0), b, a)), yy));
		else if (cell->type == ID($bwmux))
			ez->assume(ez->vec_eq(ez->vec_ite(s, b, a), yy));
		else
			ez->assume(ez->vec_eq(ez->vec_ite(s.at(0), b, a), yy));

		if (model_undef)
		{
			std::vector<int> undef_a = importUndefSigSpec(cell->getPort(ID::A), timestep);
			std::vector<int> undef_b = importUndefSigSpec(cell->getPort(ID::B), timestep);
			std::vector<int> undef_s = importUndefSigSpec(cell->getPort(ID::S), timestep);
			std::vector<int> undef_y = importUndefSigSpec(cell->getPort(ID::Y), timestep);

			std::vector<int> unequal_ab = ez->vec_not(ez->vec_iff(a, b));
			std::vector<int> undef_ab = ez->vec_or(unequal_ab, ez->vec_or(undef_a, undef_b));
			std::vector<int> yX;
			if (cell->type == ID($bwmux))
				yX = ez->vec_ite(undef_s, undef_ab, ez->vec_ite(s, undef_b, undef_a));
			else
				yX = ez->vec_ite(undef_s.at(0), undef_ab, ez->vec_ite(s.at(0), undef_b, undef_a));
			ez->assume(ez->vec_eq(yX, undef_y));
			undefGating(y, yy, undef_y);
		}
		return true;
	}
